"""Run INTRA-1A downloads, sealed CSV replays, or a clearly synthetic demo."""

import argparse
import csv
import hashlib
import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from dx27.adapters.calendars.xnys import load_xnys_calendar
from dx27.adapters.intraday.data import CSV_FIELDS, aware_time, download_alpaca, load_csv
from dx27.application.intraday_replay import IntradayLedgerReplay
from dx27.core.models.execution_costs import ExecutionCosts
from dx27.domains.intraday.replay_config import IntradayReplayConfig
from dx27.domains.intraday.selection.opening_volume import OpeningVolumeConfig


def read_config(path=None, decision_start=None):
    values = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    if "costs" in values:
        values["costs"] = ExecutionCosts(**values["costs"])
    if values.get("opening_volume") is not None:
        values["opening_volume"] = OpeningVolumeConfig(**values["opening_volume"])
    if values.get("decision_start"):
        values["decision_start"] = date.fromisoformat(values["decision_start"])
    config = IntradayReplayConfig(**values)
    return replace(config, decision_start=date.fromisoformat(decision_start)) if decision_start else config


def write_report(result, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "summary.json").write_text(json.dumps(result.summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tables = [("fills.csv", result.fills), ("trades.csv", result.trades),
              ("equity.csv", result.equity), ("daily.csv", result.daily),
              ("decisions.csv", result.decisions), ("data-quality.csv", result.quality)]
    if result.summary.get("task") == "INTRA-1B" or result.summary.get("underlying_strategy") == "INTRA-1B":
        tables.append(("selection.csv", result.selections))
    for filename, rows in tables:
        keys = list(dict.fromkeys(key for row in rows for key in row))
        with (output / filename).open("w", newline="", encoding="utf-8") as stream:
            if keys:
                writer = csv.DictWriter(stream, fieldnames=keys)
                writer.writeheader()
                writer.writerows(rows)
    summary = result.summary
    synthetic = summary["input"].get("source") == "SYNTHETIC_DEMO"
    notice = "**合成演示数据：结果仅用于软件验收。**" if synthetic else "历史行情回放；输入可用时间假设为 K 线结束，不构成原始时点或盈利能力验证。"
    pnl = f'{summary["net_pnl"]:.2f}' if summary["net_pnl"] is not None else "不可用：数据不完整或仍有持仓"
    (output / "report.md").write_text(
        f'# {summary["task"]} 交易账本\n\n{notice}\n\n'
        f'- 回放状态：{summary["status"]}\n'
        f'- 标的：{", ".join(summary["symbols"])}\n'
        f'- 交易日：{summary["sessions"]}；已结束交易：{summary["trades"]}\n'
        f'- 期末现金：{summary["ending_cash"]:.2f}；期末权益：{summary["ending_equity"]:.2f}\n'
        f'- 扣费后净损益：{pnl}\n'
        f'- 佣金：{summary["total_commission"]:.2f}；模型点差成本：{summary["total_spread_cost"]:.2f}；'
        f'模型滑点成本：{summary["total_slippage_cost"]:.2f}\n'
        f'- 现金流、交易成本与账户权益核对：通过\n\n'
        '逐笔成交见 fills.csv，交易损益见 trades.csv，每分钟权益见 equity.csv，'
        '逐日状态见 daily.csv，信号和拒绝原因见 decisions.csv，缺失与歧义见 data-quality.csv。\n\n'
        '成交使用明确配置的点差、滑点和费用，未模拟真实盘口队列与市场冲击。'
        '本任务未测试策略有效性，未启用生产或券商下单。\n', encoding="utf-8")


def create_demo(path):
    """Two full sessions, including the 2025 Thanksgiving early close."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    calendar = load_xnys_calendar(date(2025, 11, 26), date(2025, 11, 28))
    symbols = ("SPY", "QQQ", "IWM")
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for day_index, session in enumerate(calendar.sessions):
            timestamp, minute = session.opens_at, 0
            while timestamp < session.closes_at:
                for index, symbol in enumerate(symbols):
                    opening = 100 + index * 25 + day_index * 0.5 + minute * 0.005
                    writer.writerow(dict(symbol=symbol, timestamp=timestamp.isoformat(),
                                         open=opening, high=opening + 0.014, low=opening - 0.01,
                                         close=opening + 0.004, volume=100_000))
                timestamp += timedelta(minutes=1)
                minute += 1
    metadata = dict(source="SYNTHETIC_DEMO", symbols=list(symbols), bar_label="interval_start",
                    csv_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), original_cutoff_verified=False)
    path.with_suffix(path.suffix + ".metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    replay = commands.add_parser("replay", help="replay a one-minute CSV")
    replay.add_argument("--input", required=True)
    replay.add_argument("--output", required=True, help="new report directory")
    replay.add_argument("--config")
    replay.add_argument("--decision-start", help="YYYY-MM-DD; earlier sessions warm indicators only")
    demo = commands.add_parser("demo", help="generate labeled synthetic data and a report")
    demo.add_argument("--output", required=True, help="new directory")
    download = commands.add_parser("download", help="historical SIP bars; no broker actions")
    download.add_argument("--symbols", required=True, help="comma-separated symbols")
    download.add_argument("--start", required=True, help="inclusive ISO timestamp with offset")
    download.add_argument("--end", required=True, help="exclusive ISO timestamp with offset, >=15 minutes old")
    download.add_argument("--output", required=True, help="new CSV path")
    args = parser.parse_args(argv)
    try:
        if args.command == "download":
            metadata = download_alpaca(args.symbols.split(","), aware_time(args.start), aware_time(args.end), args.output)
            print(json.dumps(dict(status="DOWNLOADED", rows=metadata["rows"], csv_sha256=metadata["csv_sha256"])))
            return 0
        if args.command == "demo":
            root = Path(args.output)
            if root.exists():
                raise FileExistsError("demo directory already exists; choose a new path")
            root.mkdir(parents=True)
            path = root / "synthetic-minute-bars.csv"
            create_demo(path)
            config, output = IntradayReplayConfig(), root / "report"
        else:
            path, output = Path(args.input), Path(args.output)
            config = read_config(args.config, args.decision_start)
        result = IntradayLedgerReplay(config).run(load_csv(path))
        write_report(result, output)
        print(json.dumps(dict(status=result.summary["status"], output=str(output),
                              trades=result.summary["trades"], net_pnl=result.summary["net_pnl"])))
        return 0 if result.summary["status"] == "COMPLETE_REPLAY" else 2
    except (ValueError, RuntimeError, OSError, TypeError, KeyError) as exc:
        parser.exit(1, f"INTRA-1A failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
