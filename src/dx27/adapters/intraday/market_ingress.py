"""Convert/inspect sealed historical event traces, without network access."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

from dx27.adapters.intraday.data import aware_time, load_csv
from dx27.adapters.intraday.recorded_shadow import _hash, _json
from dx27.application.market_ingress import compile_ingress, session_grid
from dx27.core.models.market_context import MarketContext
from dx27.domains.intraday.market_event import MarketEvent


def event_clock(value):
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("event time requires an offset")
    return at.astimezone(timezone.utc)


def event_from_dict(values):
    values = dict(values)
    for key in ("available_at", "received_at", "through"):
        if values.get(key) is not None:
            values[key] = event_clock(values[key])
    if values.get("bar") is not None:
        bar = dict(values["bar"])
        bar["timestamp"] = aware_time(bar["timestamp"])
        values["bar"] = MarketContext(**bar)
    return MarketEvent(**values)


def historical_events(dataset):
    """Declare assumed receipt at interval end; never claim observed live timings."""
    _, grid = session_grid(dataset)
    expected = set(grid)
    source = dataset.provenance.get("source", "LOCAL_CSV_UNVERIFIED")
    yield MarketEvent("history-connect", source, "historical", 1, "CONNECT", grid[0], grid[0])
    sequence = 1
    for bar in dataset.bars:
        if bar.timestamp not in expected:
            continue
        sequence += 1
        at = bar.timestamp + timedelta(minutes=1)
        identity = "bar-" + _hash(_json((bar.symbol, bar.timestamp)))[:40]
        yield MarketEvent(identity, source, "historical", sequence, "BAR", at, at, bar, 1)


def load_events(path, source):
    path = Path(path)
    raw = path.read_bytes()
    metadata = path.with_suffix(path.suffix + ".metadata.json")
    if metadata.exists():
        seal = json.loads(metadata.read_text(encoding="utf-8"))
        if seal.get("events_file_sha256") != hashlib.sha256(raw).hexdigest() or seal.get("source_csv_sha256") != source.provenance.get("csv_sha256"):
            raise ValueError("event file/source seal mismatch")
    return tuple(event_from_dict(json.loads(line)) for line in raw.decode("utf-8").splitlines() if line.strip())


def write_events(dataset, output):
    output = Path(output)
    metadata = output.with_suffix(output.suffix + ".metadata.json")
    if output.exists() or metadata.exists():
        raise FileExistsError("choose new event output paths")
    raw = ("\n".join(_json(asdict(event)) for event in historical_events(dataset)) + "\n").encode()
    seal = dict(contract="P2-H4:1", events_file_sha256=hashlib.sha256(raw).hexdigest(),
                source_csv_sha256=dataset.provenance.get("csv_sha256"),
                receipt_times="ASSUMED_AT_MINUTE_END", real_broker_orders_enabled=False,
                realtime_data_verified=False, original_cutoff_verified=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        with output.open("xb") as stream:
            created.append(output)
            stream.write(raw)
        with metadata.open("x", encoding="utf-8") as stream:
            created.append(metadata)
            stream.write(_json(seal) + "\n")
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return seal


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("convert")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p = commands.add_parser("inspect")
    p.add_argument("--input", required=True)
    p.add_argument("--events", help="omit for the canonical historical assumption")
    args = parser.parse_args(argv)
    try:
        dataset = load_csv(args.input)
        if args.command == "convert":
            print(_json(write_events(dataset, args.output)))
            return 0
        events = load_events(args.events, dataset) if args.events else historical_events(dataset)
        receipt = compile_ingress(dataset, events).receipt()
        print(_json(receipt))
        return 0 if receipt["status"] == "COMPLETE_INGRESS" else 2
    except (ValueError, TypeError, KeyError, OSError, AttributeError):
        print(_json(dict(task="P2-H4", status="FAILED", error_code="INVALID_EVENT_INPUT", real_broker_orders_enabled=False)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
