"""Readable, static market observations from existing typed sensor projections.

This renderer compares measured values; it does not classify a global regime,
run a detector, forecast outcomes, or promote descriptive data to causal proof.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
import math
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo


_BERLIN = ZoneInfo("Europe/Berlin")
_STATUSES = {
    "AVAILABLE": "可用",
    "SOURCE_ERROR": "来源采集失败",
    "UNSUPPORTED_SESSION": "来源不覆盖该交易日",
    "UNAVAILABLE": "缺少数据",
    "STALE": "数据滞后",
    "INSUFFICIENT_HISTORY": "历史长度不足",
    "NORMALIZED_DESCRIPTIVE": "已取得并解析",
}
_LABELS = {
    "spy_return_20": "SPY · 标普 500 市值加权",
    "rsp_return_20": "RSP · 标普 500 等权",
    "qqq_return_20_derived": "QQQ · 纳斯达克 100",
    "iwm_return_20_derived": "IWM · 罗素 2000",
    "rsp_spy_relative_20": "RSP / SPY · 等权相对表现",
    "qqq_spy_relative_20": "QQQ / SPY · 纳指相对表现",
    "iwm_spy_relative_20": "IWM / SPY · 小盘相对表现",
    "spy_rv_20": "SPY · 20 日实现波动率",
    "spy_rv_5_over_20": "SPY · 5 日 / 20 日波动率",
    "vix_level": "VIX · 30 日期权隐含波动率",
    "vix_minus_rv_20": "VIX − SPY 20 日实现波动率",
    "hy_oas_level": "美国高收益债 · 期权调整利差",
    "ust_2y_level": "美国国债 · 2 年收益率",
    "ust_10y_level": "美国国债 · 10 年收益率",
    "ust_10y_minus_2y": "美国国债 · 10 年 − 2 年利差",
    "sofr_minus_effr": "SOFR − EFFR · 融资利差",
    "constituent_breadth_20": "成分股上涨比例",
    "top7_weight": "头部七只股票权重",
    "mega7_return_contribution_20": "Mega7 的指数回报贡献",
}
_SECTORS = {
    "XLK": "科技",
    "XLF": "金融",
    "XLE": "能源",
    "XLV": "医疗",
    "XLI": "工业",
    "XLP": "必需消费",
    "XLY": "可选消费",
    "XLU": "公用事业",
    "XLB": "材料",
    "XLRE": "房地产",
    "XLC": "通信服务",
}
_GROUPS = (
    (
        "股票表现与分化",
        (
            "spy_return_20",
            "rsp_return_20",
            "qqq_return_20_derived",
            "iwm_return_20_derived",
            "rsp_spy_relative_20",
            "qqq_spy_relative_20",
            "iwm_spy_relative_20",
        ),
    ),
    (
        "波动与信用",
        (
            "vix_level",
            "spy_rv_20",
            "spy_rv_5_over_20",
            "vix_minus_rv_20",
            "hy_oas_level",
        ),
    ),
    (
        "利率与融资",
        ("ust_2y_level", "ust_10y_level", "ust_10y_minus_2y", "sofr_minus_effr"),
    ),
)


def _entries(market: dict | None) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    if not isinstance(market, dict):
        return entries
    for dimension in market.values():
        if not isinstance(dimension, list):
            continue
        for entry in dimension:
            if isinstance(entry, dict) and isinstance(entry.get("sensor_id"), str):
                entries.setdefault(entry["sensor_id"], entry)
    return entries


def _evidence_entries(market: dict | None) -> list[dict]:
    result, seen = [], set()
    if not isinstance(market, dict):
        return result
    for dimension in market.values():
        if not isinstance(dimension, list):
            continue
        for entry in dimension:
            if not isinstance(entry, dict) or not isinstance(
                entry.get("sensor_id"), str
            ):
                continue
            identity = entry.get("measurement_ref") or repr(entry)
            if identity not in seen:
                result.append(entry)
                seen.add(identity)
    return result


def _amount(entry: dict | None) -> float | None:
    state = (entry or {}).get("state", {})
    if state.get("data_status") != "AVAILABLE":
        return None
    value = state.get("value")
    amount = value.get("amount") if isinstance(value, dict) else None
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return None
    return float(amount) if math.isfinite(amount) else None


def _time(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "未提供"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return value
        return parsed.astimezone(_BERLIN).strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return value


def _state_date(entry: dict | None) -> str:
    state = (entry or {}).get("state", {})
    if not state.get("evidence_refs") and _amount(entry) is None:
        return "—"
    label = state.get("observation_label") or state.get("observation_date")
    return str(label) if label else _time(state.get("state_as_of"))


def _signed(value: float, precision: int = 2) -> str:
    # Do not display rounded zero with an apparent direction.
    if round(value, precision) == 0:
        return f"{0:.{precision}f}"
    return f"{value:+.{precision}f}"


def _convert(amount: float, unit: str) -> float:
    return math.expm1(amount) * 100 if unit == "log_return" else amount


def _unit(entry: dict | None) -> str:
    value = (entry or {}).get("state", {}).get("value")
    return value.get("unit", "") if isinstance(value, dict) else ""


def _format_value(entry: dict | None) -> str:
    amount = _amount(entry)
    if amount is None:
        status = (entry or {}).get("state", {}).get("data_status", "UNAVAILABLE")
        return "— · " + _STATUSES.get(status, "不可用")
    unit = _unit(entry)
    if unit == "log_return":
        return _signed(_convert(amount, unit)) + "%"
    if unit in {"percent_annualized", "percent_per_annum"}:
        return f"{amount:.2f}%"
    if unit == "percentage_points":
        return _signed(amount) + " 个百分点"
    if unit == "basis_points":
        return f"{amount:.2f} bp"
    if unit == "ratio":
        return f"{amount:.2f} 倍"
    if unit == "fraction":
        return f"{amount * 100:.2f}%"
    return f"{amount:.2f}" + (" " + unit if unit else "")


def _comparison(current: dict | None, previous: dict | None) -> str:
    amount, old = _amount(current), _amount(previous)
    if amount is None:
        return "当前不可用，无法比较"
    if old is None:
        return "前次不可用，无法比较"
    unit = _unit(current)
    if unit != _unit(previous):
        return "单位不同，无法比较"
    if current["state"].get("state_as_of") == previous["state"].get("state_as_of"):
        if amount == old:
            return "仍为同一条观测，尚无新数据"
        return "同一观测时点；数值差 " + _delta(amount, old, unit)
    return _delta(amount, old, unit)


def _delta(amount: float, previous: float, unit: str) -> str:
    difference = _convert(amount, unit) - _convert(previous, unit)
    if unit in {
        "log_return",
        "percent_annualized",
        "percent_per_annum",
        "percentage_points",
    }:
        return _signed(difference) + " 个百分点"
    if unit == "fraction":
        return _signed(difference * 100) + " 个百分点"
    if unit == "basis_points":
        return _signed(difference) + " bp"
    if unit == "ratio":
        return _signed(difference) + " 倍"
    return _signed(difference) + (" " + unit if unit else "")


def _with_derived(entries: dict[str, dict]) -> dict[str, dict]:
    result = dict(entries)
    spy = entries.get("spy_return_20")
    for symbol in ("qqq", "iwm"):
        relative = entries.get(symbol + "_spy_relative_20")
        if (
            _amount(spy) is None
            or _amount(relative) is None
            or _unit(spy) != "log_return"
            or _unit(relative) != "log_return"
            or spy["state"].get("state_as_of") != relative["state"].get("state_as_of")
        ):
            continue
        state = dict(relative["state"])
        state["value"] = {
            "amount": _amount(spy) + _amount(relative),
            "unit": "log_return",
        }
        state["qualifiers"] = list(state.get("qualifiers", [])) + [
            "DERIVED_FROM_SPY_AND_RELATIVE"
        ]
        sensor_id = symbol + "_return_20_derived"
        result[sensor_id] = {"sensor_id": sensor_id, "state": state}
    return result


def observation_facts(report: dict) -> list[str]:
    """Describe available measurements without adding forecast/risk thresholds."""
    current = _entries(report.get("market_now"))
    previous = _entries(report.get("previous_market_now"))
    facts: list[str] = []
    spy, rsp = current.get("spy_return_20"), current.get("rsp_return_20")
    if (
        _amount(spy) is not None
        and _amount(rsp) is not None
        and spy["state"].get("state_as_of") == rsp["state"].get("state_as_of")
    ):
        facts.append(
            f"过去 20 个交易日，SPY {_format_value(spy)}，RSP {_format_value(rsp)}。"
        )
    relative = current.get("rsp_spy_relative_20")
    value = _amount(relative)
    if value is not None:
        direction = "落后于" if value < 0 else "领先于" if value > 0 else "与"
        performance = (
            f"{abs(_convert(value, _unit(relative))):.2f}%"
            if value != 0
            else "表现相同"
        )
        facts.append(
            f"等权组合{direction}市值加权组合 {performance}（20 日回报倍数之比）。"
        )
    differences = []
    for sensor_id, label in (
        ("qqq_spy_relative_20", "QQQ"),
        ("iwm_spy_relative_20", "IWM"),
    ):
        entry = current.get(sensor_id)
        if _amount(entry) is not None:
            differences.append(f"{label} 相对 SPY {_format_value(entry)}")
    if differences:
        facts.append("；".join(differences) + "（过去 20 个交易日）。")
    pressure = []
    for sensor_id, label in (("vix_level", "VIX"), ("hy_oas_level", "高收益债利差")):
        entry, old = current.get(sensor_id), previous.get(sensor_id)
        if _amount(entry) is not None:
            comparison = ""
            if _amount(old) is not None:
                change = _comparison(entry, old)
                comparison = (
                    "，" + change
                    if change == "仍为同一条观测，尚无新数据"
                    else "，较前次 " + change
                )
            pressure.append(label + " " + _format_value(entry) + comparison)
    if pressure:
        facts.append("；".join(pressure) + "。")
    return facts or ["当前可用观测不足，暂时无法描述股票分化或波动、信用变化。"]


def _sector_members(market: dict | None) -> dict[str, dict]:
    """Preserve all member contexts even though they share one sensor ID."""
    result = {}
    if not isinstance(market, dict):
        return result
    for entry in market.get("leadership", []):
        if entry.get("sensor_id") != "sector_relative_20":
            continue
        state = entry.get("state", {})
        value = state.get("value")
        members = value.get("members", []) if isinstance(value, dict) else []
        if members:
            for member in members:
                symbol = str(member.get("subject_id", "")).upper()
                member_state = {
                    **state,
                    "value": {"unit": value.get("unit"), "amount": member.get("value")},
                }
                result[symbol] = {**entry, "state": member_state}
        else:
            qualifiers = state.get("qualifiers", [])
            subject = next(
                (
                    q.split(":", 1)[1]
                    for q in qualifiers
                    if q.startswith("SECTOR_SUBJECT:")
                ),
                None,
            )
            feed = next(
                (
                    q.split(":", 1)[1]
                    for q in qualifiers
                    if q.startswith("SECTOR_FEED:")
                ),
                None,
            )
            if subject or feed:
                result[str(subject or feed).upper()] = entry
    return result


def _rows(report: dict) -> list[tuple[str, list[tuple[str, str, str, str]]]]:
    current = _with_derived(_entries(report.get("market_now")))
    previous = _with_derived(_entries(report.get("previous_market_now")))
    groups = []
    for title, sensors in _GROUPS:
        rows = []
        for sensor_id in sensors:
            entry, old = current.get(sensor_id), previous.get(sensor_id)
            rows.append(
                (
                    _LABELS[sensor_id],
                    _format_value(entry),
                    _comparison(entry, old),
                    _state_date(entry),
                )
            )
        groups.append((title, rows))
    sectors = _sector_members(report.get("market_now"))
    old_sectors = _sector_members(report.get("previous_market_now"))
    if sectors:
        rows = []
        for symbol in sorted(
            sectors,
            key=lambda symbol: (
                list(_SECTORS).index(symbol) if symbol in _SECTORS else 99,
                symbol,
            ),
        ):
            entry, old = sectors[symbol], old_sectors.get(symbol)
            label = _SECTORS.get(symbol, symbol) + " · " + symbol
            rows.append(
                (
                    label,
                    _format_value(entry),
                    _comparison(entry, old),
                    _state_date(entry),
                )
            )
        partial = len(sectors) != 9 or any(
            _amount(entry) is None
            or "PARTIAL_SECTOR_CONTEXT" in entry.get("state", {}).get("qualifiers", [])
            for entry in sectors.values()
        )
        title = "行业相对 SPY · 过去 20 个交易日" + (
            "（部分可用）" if partial else "（9 个行业代理）"
        )
        groups.append((title, rows))
    else:
        sector_entry = _entries(report.get("market_now")).get("sector_relative_20", {})
        groups.append(
            (
                "行业相对 SPY · 过去 20 个交易日",
                [
                    (
                        "行业相对表现向量",
                        _format_value(sector_entry),
                        "无法完整比较",
                        _state_date(sector_entry),
                    )
                ],
            )
        )
    return groups


def _gaps(report: dict) -> list[str]:
    current = _entries(report.get("market_now"))
    gaps = [
        "暂无真实成分股广度、头部权重及 Mega7 回报贡献；不能直接回答由多少股票推动指数。",
        "RSP 是标普 500 等权，QQQ 是纳斯达克 100，IWM 是罗素 2000；它们是不同组别的代理，并非 Mega7 与其余股票的精确拆分。",
        "行业观察覆盖已登记的 9 只行业 ETF，不是完整的 11 行业市场广度。",
    ]
    unavailable = []
    for sensor_id in ("spy_return_20", "rsp_return_20", "vix_level", "hy_oas_level"):
        entry = current.get(sensor_id)
        if _amount(entry) is None:
            status = (entry or {}).get("state", {}).get("data_status", "UNAVAILABLE")
            unavailable.append(
                _LABELS[sensor_id] + "：" + _STATUSES.get(status, "不可用")
            )
    if unavailable:
        gaps.append("本次缺口：" + "；".join(unavailable) + "。")
    older = []
    session_id = str(report.get("session_id", ""))
    for sensor_id in ("vix_level", "hy_oas_level", "ust_2y_level", "ust_10y_level"):
        entry = current.get(sensor_id)
        state = (entry or {}).get("state", {})
        label = state.get("observation_label") or state.get("observation_date")
        if _amount(entry) is not None and isinstance(label, str) and label < session_id:
            older.append(_LABELS[sensor_id] + "最新观测 " + label)
    if older:
        gaps.append(
            "较早日期的观测："
            + "；".join(older)
            + "。本次取回不意味着它们产生了今日新数据。"
        )
    if not isinstance(report.get("previous_market_now"), dict):
        gaps.append("暂无前次完整观察，所有前次变化均留空，不推断为没有变化。")
    return gaps


def _safe_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    if parts.hostname == "fred.stlouisfed.org":
        series_id = parse_qs(parts.query).get("id", [""])[0]
        if series_id and all(
            character.isalnum() or character == "_" for character in series_id
        ):
            return "https://fred.stlouisfed.org/series/" + quote(series_id, safe="")
    # Retrieval parameters can contain credentials; provenance needs only origin/path.
    return urlunsplit((parts.scheme, parts.hostname, parts.path, "", ""))


def _coverage(report: dict) -> str:
    market = report.get("market_now") or {}
    coverage = market.get("coverage") or report.get("coverage") or {}
    required = coverage.get("active_required", {})
    available, expected = required.get("available"), required.get("expected")
    if isinstance(available, int) and isinstance(expected, int):
        return f"必要测量 {available} / {expected} 可用"
    return "按各项实际可用性展示"


def _method_notes() -> list[str]:
    return [
        "股票及行业表现覆盖最近 20 个交易日。对比列是这项滚动指标相对前次观察的变化，不是当天收益。",
        "相对表现按两个组合的回报倍数之比计算，再减去 1；不是两个普通收益率直接相减。QQQ/IWM 的绝对表现由 SPY 与相对表现同日观测推导。",
        "VIX 是约 30 日预期波动率；实现波动率来自过去 20 个交易日。两者期限和含义不同，差值只是代理观察。",
        "数值中的 % 表示回报、年化波动率或年化利率，具体由行名区分；bp 表示基点，100 bp = 1 个百分点。",
        "对比按本次取得的历史版本重算，不是昨天当时已知的报告；历史可包含供应商修订。观测日期使用明确的来源标签；未提供标签时显示窗口结束时点。",
        "只描述观测，不发布变化告警、综合风险等级或未来概率。原有研究的数据准入状态仍未通过。",
    ]


def _md(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict) -> str:
    """Return a Chinese observation report suitable for ordinary Markdown readers."""
    previous = report.get("previous_session_id") or "暂无"
    lines = [
        "# Sentinel · 市场观察",
        "",
        f"观察交易日：**{_md(report.get('session_id', '未提供'))}** · 前次对比交易日：{_md(previous)}",
        f"生成时间：{_md(_time(report.get('generated_at')))} · 最新数据取回版本",
        "",
        _coverage(report) + "。本页描述市场，不输出预测或综合风险等级。",
        "",
        "## 一分钟观察",
        "",
        *["- " + _md(fact) for fact in observation_facts(report)],
        "",
    ]
    for title, rows in _rows(report):
        lines.extend(
            [
                "## " + title,
                "",
                "| 观察项 | 当前值 | 相对前次变化 | 观测日期 / 窗口结束 |",
                "| --- | ---: | --- | --- |",
            ]
        )
        lines.extend(
            "| " + " | ".join(_md(cell) for cell in row) + " |" for row in rows
        )
        lines.append("")
    lines.extend(
        [
            "## 尚不能回答的部分",
            "",
            *["- " + _md(gap) for gap in _gaps(report)],
            "",
            "## 口径与来源",
            "",
            *["- " + note for note in _method_notes()],
            "",
            "数据观测时间与取回时间分开记录；取回时间不是数据发布或市场发生时间。",
            "",
            "| 输入 | 来源 | 取回时间（柏林） | 采集结果 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for source in report.get("source_results", []):
        lines.append(
            "| "
            + " | ".join(
                _md(cell)
                for cell in (
                    source.get("feed_id", "未提供"),
                    source.get("source_id", "未提供"),
                    _time(source.get("first_seen_at")),
                    _STATUSES.get(source.get("status"), source.get("status", "未提供")),
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_html(report: dict) -> str:
    """Return a standalone, dependency-free HTML page with escaped evidence."""
    e = lambda value: escape(str(value), quote=True)
    previous = report.get("previous_session_id") or "暂无"
    facts = "".join(
        f'<li><span class="fact-index">{index:02d}</span><p>{e(fact)}</p></li>'
        for index, fact in enumerate(observation_facts(report), 1)
    )
    sections = []
    for title, rows in _rows(report):
        body = "".join(
            "<tr>" + "".join(f"<td>{e(cell)}</td>" for cell in row) + "</tr>"
            for row in rows
        )
        sections.append(
            f'<section class="measurement"><h2>{e(title)}</h2><div class="table-wrap">'
            "<table><thead><tr><th>观察项</th><th>当前值</th><th>相对前次变化</th><th>观测日期 / 窗口结束</th>"
            f"</tr></thead><tbody>{body}</tbody></table></div></section>"
        )
    gaps = "".join(f"<li>{e(gap)}</li>" for gap in _gaps(report))
    notes = "".join(f"<li>{e(note)}</li>" for note in _method_notes())
    source_rows = []
    for source in report.get("source_results", []):
        url = _safe_url(source.get("url"))
        source_label = e(source.get("source_id", "未提供"))
        source_link = (
            f'<a href="{e(url)}" rel="noreferrer">{source_label}</a>'
            if url
            else source_label
        )
        source_rows.append(
            "<tr>"
            f'<td>{e(source.get("feed_id", "未提供"))}</td><td>{source_link}</td>'
            f'<td>{e(_time(source.get("first_seen_at")))}</td>'
            f'<td>{e(_STATUSES.get(source.get("status"), source.get("status", "未提供")))}</td>'
            f'<td><code>{e(source.get("capture_id", "未提供"))}</code></td></tr>'
        )
    evidence_rows = []
    for entry in _evidence_entries(report.get("market_now")):
        sensor_id = entry["sensor_id"]
        state = entry.get("state", {})
        label = _LABELS.get(sensor_id, sensor_id)
        if sensor_id == "sector_relative_20":
            feed = next(
                (
                    q.split(":", 1)[1]
                    for q in state.get("qualifiers", [])
                    if q.startswith("SECTOR_FEED:")
                ),
                "",
            )
            label = "行业相对表现" + (" · " + feed.upper() if feed else "")
        evidence_rows.append(
            "<tr>"
            f"<td>{e(label)}</td>"
            f'<td>{e(_time(state.get("state_as_of")))}</td>'
            f'<td><code>{e(state.get("method_id", "未提供"))}</code></td>'
            f'<td><code>{e(entry.get("measurement_ref", "未提供"))}</code></td></tr>'
        )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sentinel 市场观察 · {e(report.get("session_id", ""))}</title>
<style>
:root{{--ink:#182b32;--muted:#627178;--paper:#f5f4ef;--line:#dde1dc;--accent:#136c66;--white:#fff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
main{{max-width:1180px;margin:auto;padding:42px 32px 70px}}header{{display:flex;justify-content:space-between;gap:32px;padding-bottom:30px;border-bottom:2px solid var(--ink)}}
.eyebrow{{font-size:11px;letter-spacing:.18em;color:var(--accent);font-weight:700}}h1{{font-size:38px;line-height:1.3;letter-spacing:-.04em;margin:12px 0}}h2{{font-size:21px;margin:0 0 18px;line-height:1.4}}
.subtitle,.meta,.scope{{color:var(--muted);font-size:13px}}.meta{{text-align:right;padding-top:24px;min-width:225px}}.session{{font-size:21px;color:var(--ink);font-variant-numeric:tabular-nums}}
.badge{{display:inline-block;border:1px solid #b2cac3;border-radius:4px;color:var(--accent);padding:3px 9px;font-size:11px;letter-spacing:.04em;margin-bottom:14px}}
.summary{{background:var(--ink);color:#eff7f4;border-radius:8px;padding:28px 30px;margin:26px 0 12px}}.summary h2{{font-size:18px;color:#b9d8cc}}.facts{{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:1fr 1fr;gap:23px 34px}}
.facts li{{display:flex;gap:14px;align-items:baseline}}.fact-index{{color:#80b4a3;font-size:12px;font-variant-numeric:tabular-nums}}.facts p{{margin:0;font-size:15px}}
.scope{{margin:0 0 30px;padding:0 2px}}.measurement{{margin:30px 0;background:var(--white);border:1px solid var(--line);border-radius:8px;padding:25px 28px}}
.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th{{font-weight:500;text-align:left;color:var(--muted);padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap}}
td{{padding:13px 12px;border-bottom:1px solid #eef0ec;vertical-align:top}}td:first-child,th:first-child{{padding-left:0}}td:nth-child(2){{font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}}td:nth-child(3){{font-variant-numeric:tabular-nums;color:#53646c}}tr:last-child td{{border-bottom:0}}
.gaps{{padding:24px 28px;border-left:3px solid #a99772;background:#efede4;border-radius:0 6px 6px 0}}.gaps h2{{font-size:17px}}.gaps ul,.notes{{margin:0;padding-left:20px}}.gaps li,.notes li{{margin:8px 0}}
details{{margin-top:26px;border-top:1px solid var(--line);padding-top:20px;color:var(--muted);font-size:13px}}summary{{cursor:pointer;font-weight:600;color:var(--ink)}}details .table-wrap{{margin-top:20px}}details h3{{font-size:14px;color:var(--ink);margin:24px 0 8px}}code{{font-size:10px;overflow-wrap:anywhere}}a{{color:var(--accent)}}footer{{margin-top:30px;font-size:11px;letter-spacing:.06em;color:var(--muted)}}
@media(max-width:720px){{main{{padding:25px 18px 45px}}header{{display:block}}h1{{font-size:32px}}.meta{{text-align:left;padding-top:12px}}.facts{{grid-template-columns:1fr}}.summary{{padding:23px}}.measurement{{padding:20px 18px}}table{{min-width:660px}}}}
@media print{{body{{background:white}}main{{padding:15px}}.summary{{background:#eee;color:var(--ink)}}.summary h2,.fact-index{{color:var(--ink)}}details{{display:block}}section{{break-inside:avoid}}}}
</style></head><body><main>
<header><div><div class="eyebrow">SENTINEL / MARKET OBSERVATION</div><h1>市场现在是什么样</h1><div class="subtitle">股票分化 · 波动 · 信用 · 利率</div></div>
<div class="meta"><span class="badge">最新版本 · 描述性观察</span><div class="session">{e(report.get("session_id", "未提供"))}</div><div>观察交易日 · 对比 {e(previous)}</div><div>生成 {e(_time(report.get("generated_at")))}</div></div></header>
<section class="summary"><h2>一分钟观察</h2><ol class="facts">{facts}</ol></section>
<p class="scope">{e(_coverage(report))}。以下变化是各项观测的事实比较，不是转折预警或未来概率。</p>
{''.join(sections)}
<section class="gaps"><h2>尚不能回答的部分</h2><ul>{gaps}</ul></section>
<details><summary>展开口径、取回时间与来源记录</summary><h3>如何阅读</h3><ul class="notes">{notes}</ul>
<h3>输入来源与取回时间</h3><p>观测日期显示市场或指标对应的时间；取回时间显示我们何时收到数据，两者不能互相替代。</p>
<div class="table-wrap"><table><thead><tr><th>输入</th><th>来源</th><th>取回时间（柏林）</th><th>采集结果</th><th>原始记录</th></tr></thead><tbody>{''.join(source_rows)}</tbody></table></div>
<h3>观测时点与测量记录</h3><div class="table-wrap"><table><thead><tr><th>观察项</th><th>观测时点（柏林）</th><th>方法记录</th><th>测量记录</th></tr></thead><tbody>{''.join(evidence_rows)}</tbody></table></div>
</details><footer>SENTINEL · 可核对的市场观察 · {e(_time(report.get("generated_at")))}</footer>
</main></body></html>"""
