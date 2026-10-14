"""Sealed historical closed-loop simulation with deterministic offline recovery."""

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from dx27.adapters.intraday.cli import read_config, write_report
from dx27.adapters.intraday.order_book import OfflineOrderBook
from dx27.adapters.intraday.recorded_shadow import ShadowJournal, _hash, _json, manifest_for
from dx27.adapters.intraday.scripted_broker import ScriptedBroker
from dx27.adapters.intraday.data import load_csv
from dx27.application.intraday_closed_loop import ClosedLoopReplay
from dx27.domains.intraday.execution_profile import HistoricalExecutionProfile
from dx27.domains.intraday.replay_config import IntradayReplayConfig


def closed_loop_manifest(dataset, config, profile):
    manifest = dict(manifest_for(dataset, config), contract_version="P2-H2:1",
                    mode="HISTORICAL_CLOSED_LOOP", profile=asdict(profile),
                    recovery="DETERMINISTIC_OFFLINE_REBUILD")
    return manifest


def run_closed_loop(dataset, journal, config=None, profile=None, *, stop_after_minutes=None, control=None):
    config = config or IntradayReplayConfig()
    profile = profile or HistoricalExecutionProfile()
    if stop_after_minutes is not None and (isinstance(stop_after_minutes, bool) or not isinstance(stop_after_minutes, int) or stop_after_minutes < 1):
        raise ValueError("stop_after_minutes requires a positive integer")
    manifest = closed_loop_manifest(dataset, config, profile)
    identity = _hash(_json(manifest))

    class Paused(Exception):
        pass

    with ShadowJournal(journal, manifest) as store:
        with TemporaryDirectory(prefix=".p2h2-rebuild-", dir=store.path.parent) as temporary:
            with OfflineOrderBook(Path(temporary) / "orders.sqlite3", "p2h2:" + identity, config.initial_cash) as book:
                with ScriptedBroker(Path(temporary) / "broker.sqlite3", "p2h2:" + identity, config.initial_cash) as broker:
                    engine = ClosedLoopReplay(config, profile, book, broker)
                    minutes, events, prior_orders = 0, 0, {}
                    stopped = False

                    def record(frame):
                        nonlocal minutes, events, prior_orders, stopped
                        current = book.journal.state["orders"]
                        frame["orders"] = [deepcopy(order) for cid, order in current.items() if prior_orders.get(cid) != order]
                        # Book mutations replace state, so retained old rows are
                        # immutable to this observer; detached output stays safe.
                        prior_orders = dict(current)
                        frame["execution_events"] = deepcopy(engine.execution_events[events:])
                        events = len(engine.execution_events)
                        new = store.sequence >= store.existing
                        store.append(frame)
                        if control is not None:
                            stopped = bool(control(dict(kind=frame["kind"], as_of=frame["as_of"],
                                frames=store.sequence, committed_frames=max(store.sequence, store.existing),
                                existing_frames=store.existing, verified_prefix_frames=store.verified,
                                appended_frames=store.appended, journal_chain_sha256=store.chain,
                                account=deepcopy(frame.get("equity", [])[-1]) if frame.get("equity") else None)))
                            if stopped:
                                raise Paused()
                        if new and frame["kind"] == "MINUTE_COMPLETED":
                            minutes += 1
                            if stop_after_minutes is not None and minutes >= stop_after_minutes:
                                raise Paused()

                    result = None
                    try:
                        result = engine.run(dataset, observer=record)
                        store.append(dict(kind="RUN_COMPLETED", as_of=result.daily[-1]["session_close"],
                                          hypothetical=True, summary=result.summary))
                        if store.sequence < store.existing:
                            raise ValueError("closed-loop journal has unexpected trailing frames")
                        status = "COMPLETE_CLOSED_LOOP" if result.summary["status"] == "COMPLETE_REPLAY" else "INCOMPLETE_CLOSED_LOOP"
                    except Paused:
                        status = "STOPPED" if stopped else "PAUSED"
                    receipt = dict(task="P2-H2", status=status, manifest_sha256=identity,
                                   frames=store.sequence, verified_prefix_frames=store.verified,
                                   appended_frames=store.appended, journal_chain_sha256=store.chain,
                                   recovery="DETERMINISTIC_OFFLINE_REBUILD", simulator_rebuilt_from_start=True,
                                   real_broker_orders_enabled=False, realtime_data_verified=False,
                                   algorithm_optimization_performed=False, effectiveness="NOT_EVALUATED")
    return receipt, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--config")
    parser.add_argument("--decision-start")
    parser.add_argument("--profile", help="fixed execution scenario JSON; omitted means immediate full-fill control")
    parser.add_argument("--stop-after-minutes", type=int)
    parser.add_argument("--output", help="new optional modeled-ledger report directory")
    args = parser.parse_args(argv)
    try:
        if args.output and Path(args.output).exists():
            raise FileExistsError("report output already exists; choose a new directory")
        values = json.loads(Path(args.profile).read_text(encoding="utf-8")) if args.profile else {}
        receipt, result = run_closed_loop(load_csv(args.input), args.journal,
                                          read_config(args.config, args.decision_start), HistoricalExecutionProfile(**values),
                                          stop_after_minutes=args.stop_after_minutes)
        if result is not None and args.output:
            write_report(result, args.output)
            Path(args.output, "closed-loop-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt))
        return 0 if receipt["status"] == "COMPLETE_CLOSED_LOOP" else 3 if receipt["status"] == "PAUSED" else 2
    except (ValueError, RuntimeError, OSError, TypeError, KeyError, sqlite3.DatabaseError) as exc:
        parser.exit(1, f"closed-loop simulation failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
