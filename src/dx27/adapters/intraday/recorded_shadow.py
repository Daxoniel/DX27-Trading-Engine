"""Durable historical Shadow Mode. No network or broker execution path."""

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from importlib.metadata import version
from pathlib import Path

from dx27.adapters.intraday.cli import read_config, write_report
from dx27.adapters.intraday.data import load_csv, validate_bar
from dx27.application.intraday_replay import IntradayLedgerReplay
from dx27.domains.intraday.replay_config import IntradayReplayConfig


CONTRACT_VERSION = "P1-H:1"
GENESIS = "0" * 64


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False,
                      default=lambda v: v.isoformat() if isinstance(v, (date, datetime)) else _unsupported(v))


def _unsupported(value):
    raise TypeError("unsupported journal value")


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def manifest_for(dataset, config):
    # Seal actual parsed bars too: an in-memory dataset must not bypass CSV seals.
    digest, seen = hashlib.sha256(), set()
    for bar in sorted(dataset.bars, key=lambda b: (b.timestamp, b.symbol)):
        validate_bar(bar)
        key = (bar.timestamp, bar.symbol)
        if key in seen:
            raise ValueError("duplicate symbol/timestamp")
        seen.add(key)
        digest.update((_json(asdict(bar)) + "\n").encode("utf-8"))
    if not seen:
        raise ValueError("shadow replay requires minute data")
    return dict(contract_version=CONTRACT_VERSION, parsed_bars_sha256=digest.hexdigest(),
                input_bars=len(seen), source=dataset.provenance, config=asdict(config),
                calendar_version=version("exchange-calendars"),
                mode="RECORDED_HISTORICAL_SHADOW", broker_orders_enabled=False,
                realtime_data_verified=False, availability="ASSUMED_AT_MINUTE_END",
                recovery="DETERMINISTIC_PREFIX_REPLAY")


class ShadowJournal:
    """Atomic minute batches, hash chaining and one writer with crash-safe lease.

    Recovery rebuilds the shared engine from the sealed input and verifies each
    stored batch before appending. It never re-emits a stored hypothetical order.
    The separate SQLite lease is released by the OS if the process is killed.
    """

    def __init__(self, path, manifest):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lease = self.connection = None
        self.sequence, self.chain = 0, GENESIS
        self.appended, self.verified = 0, 0
        try:
            self.lease = sqlite3.connect(str(self.path) + ".lease.sqlite3", timeout=0)
            self.lease.execute("BEGIN EXCLUSIVE")
            self.connection = sqlite3.connect(self.path, timeout=0)
            expected = _json(manifest)
            has_metadata = self.connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone()
            if has_metadata:
                stored = self.connection.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()
                if stored is None or stored[0] != expected:
                    raise ValueError("journal input/config/calendar/contract mismatch; use a new journal")
            elif self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                raise ValueError("unrecognized historical journal database")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA journal_mode=DELETE")
            if not has_metadata:
                self.connection.execute("BEGIN IMMEDIATE")
                with self.connection:
                    self.connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                    self.connection.execute("CREATE TABLE frames (sequence INTEGER PRIMARY KEY, frame_key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, chain TEXT NOT NULL)")
                    self.connection.execute("INSERT INTO metadata VALUES ('manifest', ?)", (expected,))
            # Check the whole chain before replay, including any trailing rows.
            sequence, chain = 0, GENESIS
            for seq, key, payload, seal in self.connection.execute("SELECT sequence, frame_key, payload, chain FROM frames ORDER BY sequence"):
                sequence += 1
                if seq != sequence or seal != _hash(chain + "\n" + key + "\n" + payload):
                    raise ValueError("journal integrity failure")
                chain = seal
            self.existing = sequence
        except BaseException:
            self.close()
            raise

    def append(self, frame):
        seq = self.sequence + 1
        key = frame["kind"] + ":" + frame["as_of"]
        payload = _json(frame)
        seal = _hash(self.chain + "\n" + key + "\n" + payload)
        with self.connection:
            stored = self.connection.execute("SELECT frame_key, payload, chain FROM frames WHERE sequence=?", (seq,)).fetchone()
            if stored is not None:
                if stored != (key, payload, seal):
                    raise ValueError("reconstructed shadow prefix differs from journal; stopped")
                self.verified += 1
            else:
                if seq <= self.existing:
                    raise ValueError("journal prefix has a gap")
                self.connection.execute("INSERT INTO frames VALUES (?, ?, ?, ?)", (seq, key, payload, seal))
                self.appended += 1
        self.sequence, self.chain = seq, seal

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self.lease is not None:
            self.lease.close()
            self.lease = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def run_recorded_shadow(dataset, journal, config=None, *, stop_after_minutes=None):
    """Run or resume a sealed historical input, preserving modeled replay parity.

    stop_after_minutes is a controlled process boundary, not a partial-data run.
    A subsequent call with the same input/config resumes by verified replay.
    """
    config = config or IntradayReplayConfig()
    if stop_after_minutes is not None and (isinstance(stop_after_minutes, bool)
            or not isinstance(stop_after_minutes, int) or stop_after_minutes < 1):
        raise ValueError("stop_after_minutes must be a positive integer")
    manifest = manifest_for(dataset, config)
    if config.opening_volume is not None and dataset.provenance.get("feed") != "sip" and dataset.provenance.get("source") != "SYNTHETIC_DEMO":
        raise ValueError("opening volume requires declared SIP or synthetic data")

    class Paused(Exception):
        pass

    with ShadowJournal(journal, manifest) as store:
        minutes = 0

        def observe(frame):
            nonlocal minutes
            was_new = store.sequence >= store.existing
            store.append(frame)
            if was_new and frame["kind"] == "MINUTE_COMPLETED":
                minutes += 1
                if stop_after_minutes is not None and minutes >= stop_after_minutes:
                    raise Paused()

        result = None
        try:
            result = IntradayLedgerReplay(config).run(dataset, observer=observe)
            store.append(dict(kind="RUN_COMPLETED", as_of=result.daily[-1]["session_close"],
                              hypothetical=True, summary=result.summary))
            if store.sequence < store.existing:
                raise ValueError("journal contains unexpected trailing frames")
            status = "COMPLETE_RECORDED_SHADOW" if result.summary["status"] == "COMPLETE_REPLAY" else "INCOMPLETE_RECORDED_SHADOW"
        except Paused:
            status = "PAUSED"
        receipt = dict(task="P1-H", status=status, contract_version=CONTRACT_VERSION,
                       mode="RECORDED_HISTORICAL_SHADOW", manifest_sha256=_hash(_json(manifest)),
                       frames=store.sequence, verified_prefix_frames=store.verified,
                       appended_frames=store.appended, journal_chain_sha256=store.chain,
                       broker_orders_enabled=False, realtime_data_verified=False,
                       effectiveness="NOT_EVALUATED", recovery="DETERMINISTIC_PREFIX_REPLAY")
    return receipt, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="sealed historical one-minute CSV")
    parser.add_argument("--journal", required=True, help="SQLite journal; repeat to resume")
    parser.add_argument("--config")
    parser.add_argument("--decision-start")
    parser.add_argument("--stop-after-minutes", type=int, help="pause after this many newly committed minutes")
    parser.add_argument("--output", help="new optional modeled-ledger report directory")
    args = parser.parse_args(argv)
    try:
        if args.output and Path(args.output).exists():
            raise FileExistsError("report output already exists; use a new output directory")
        receipt, result = run_recorded_shadow(load_csv(args.input), args.journal,
                                            read_config(args.config, args.decision_start),
                                            stop_after_minutes=args.stop_after_minutes)
        if result is not None and args.output:
            write_report(result, args.output)
            Path(args.output, "shadow-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt))
        return 0 if receipt["status"] == "COMPLETE_RECORDED_SHADOW" else 3 if receipt["status"] == "PAUSED" else 2
    except sqlite3.OperationalError:
        parser.exit(1, "recorded shadow failed: journal busy or unavailable; stop the other writer or check storage\n")
    except (ValueError, RuntimeError, OSError, TypeError, KeyError, sqlite3.DatabaseError) as exc:
        parser.exit(1, f"recorded shadow failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
