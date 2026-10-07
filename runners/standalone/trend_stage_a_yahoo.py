"""Local-only Stage-A acquisition and research; no winner selection."""

import argparse
import csv
import hashlib
import json
from math import isfinite, isclose
from pathlib import Path
import time

import pandas as pd
import yfinance

from dx27.intelligence.sentinel.research.trend_models import CANDIDATES
from dx27.intelligence.sentinel.research.trend_tournament import (
    STAGE_A_SYMBOLS, REQUIRED_COLUMNS, OUTPUT_FILENAMES,
    read_csv, run_tournament, write_outputs, validate_dataframe,
)

HISTORY_PARAMETERS = dict(start="2003-01-01", end="2026-10-01", interval="1d",
                          auto_adjust=True, back_adjust=False, actions=False,
                          repair=False, keepna=False, rounding=False, raise_errors=True)
# YFINANCE_VERIFIED_PROVIDER_BEHAVIOR: auto_adjust=True adjusts all OHLC.
ADJUSTMENT_METHOD = "yfinance_history_auto_adjust_true"
CANDIDATE_IDS = tuple(c.candidate_id for c in CANDIDATES)
SPLITS = ("selection", "out_of_sample")
ARTIFACTS = ("stage_a_adjusted_daily.csv", "stage_a_data_manifest.json",
             *("tournament/" + name for name in OUTPUT_FILENAMES),
             "stage_a_aggregate.csv", "stage_a_selection_oos_delta.csv",
             "stage_a_sensitivity_aggregate.csv")


class StageADataError(ValueError):
    """Provider data failed the frozen acquisition contract."""


class StageAResearchError(ValueError):
    """Tournament artifacts failed the frozen research contract."""


def output_directory(path):
    root = next(p for p in Path(__file__).resolve().parents if (p / ".git").exists())
    destination = Path(path).expanduser().resolve()
    if destination == root or root in destination.parents:
        raise StageADataError("Output directory must be outside the Git repository")
    # Check every final destination, including pre-existing symlinks.
    for name in (*ARTIFACTS, "stage_a_artifact_hashes.json"):
        target = (destination / name).resolve()
        if target == root or root in target.parents:
            raise StageADataError("Artifact destination resolves inside the Git repository")
    return destination


def fetch_symbol(symbol):
    ticker = yfinance.Ticker(symbol)
    for attempt in range(3):
        try:
            return ticker.history(**HISTORY_PARAMETERS)
        except Exception as exc:
            if attempt == 2:
                raise StageADataError(f"{symbol}: {type(exc).__name__}: {exc}") from exc
            time.sleep((2, 5)[attempt])


def normalize_symbol(symbol, history):
    columns = ["Open", "High", "Low", "Close", "Volume"]
    if not isinstance(history, pd.DataFrame) or not history.columns.is_unique or any(
        c not in history.columns for c in columns
    ):
        raise StageADataError(f"{symbol}: missing or duplicate required OHLCV columns")
    if history.empty or not isinstance(history.index, pd.DatetimeIndex) or history.index.hasnans:
        raise StageADataError(f"{symbol}: nonempty daily DatetimeIndex required")
    frame = history.loc[:, columns].copy()
    frame.columns = list(REQUIRED_COLUMNS[2:])
    frame.insert(0, "date", [day.date().isoformat() for day in history.index])
    frame.insert(0, "symbol", symbol)
    return frame.reset_index(drop=True)


def validate_data(frame):
    try:
        bars = validate_dataframe(frame)
    except (ValueError, TypeError, OverflowError) as exc:
        raise StageADataError(str(exc)) from exc
    if {b.symbol for b in bars} != set(STAGE_A_SYMBOLS):
        raise StageADataError("Exactly the 13 Stage-A symbols are required")
    if any(not "2003-01-01" <= b.date.isoformat() <= "2026-09-30" for b in bars):
        raise StageADataError("Session date outside requested research coverage")
    coverage = {}
    for symbol in STAGE_A_SYMBOLS:
        dates = [b.date.isoformat() for b in bars if b.symbol == symbol]
        counts = dict(first_date=min(dates), last_date=max(dates), total_rows=len(dates),
                      rows_before_2005=sum(d < "2005-01-01" for d in dates),
                      selection_rows=sum("2005-01-01" <= d <= "2019-12-31" for d in dates),
                      oos_rows=sum("2020-01-01" <= d <= "2026-09-30" for d in dates))
        if counts["last_date"] != "2026-09-30":
            raise StageADataError(f"{symbol}: missing 2026-09-30")
        if not counts["selection_rows"] or not counts["oos_rows"]:
            raise StageADataError(f"{symbol}: empty selection or OOS coverage")
        if symbol != "GLD" and counts["rows_before_2005"] < 256:
            raise StageADataError(f"{symbol}: insufficient pre-2005 warm-up")
        coverage[symbol] = counts
    return coverage


def acquire_data():
    frames = [normalize_symbol(s, fetch_symbol(s)) for s in STAGE_A_SYMBOLS]
    frame = pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)
    return frame, validate_data(frame)


def write_csv(frame, path):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        frame.to_csv(handle, index=False, lineterminator="\n")


def write_json(value, path):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def data_manifest(coverage, digest):
    return dict(dataset_id="dx27.trend.stage_a.v0.1", provider="Yahoo Finance via yfinance",
                yfinance_version=yfinance.__version__, acquisition_method="Ticker.history",
                adjustment_method=ADJUSTMENT_METHOD, requested_start="2003-01-01",
                requested_end_exclusive="2026-10-01", research_last_date="2026-09-30",
                symbols=list(STAGE_A_SYMBOLS), coverage=coverage, csv_sha256=digest)


def check_tournament(directory, input_rows):
    try:
        if {p.name for p in directory.iterdir()} != set(OUTPUT_FILENAMES):
            raise StageAResearchError("Unexpected tournament artifacts")
        for name, expected in zip(OUTPUT_FILENAMES[:3], (input_rows * 9, 234, 312)):
            with (directory / name).open(encoding="utf-8", newline="") as handle:
                count = sum(1 for _ in csv.DictReader(handle))
            if count != expected:
                raise StageAResearchError(f"{name}: expected {expected} rows, got {count}")
        summary = json.loads((directory / OUTPUT_FILENAMES[3]).read_text(encoding="utf-8"))
        if (summary.get("research_id") != "dx27.trend_tournament.v0.1"
                or summary.get("winner_selected") is not False
                or summary.get("production_trend_detector_created") is not False):
            raise StageAResearchError("Frozen tournament summary contract failed")
    except (OSError, ValueError) as exc:
        raise StageAResearchError(str(exc)) from exc


def weighted(group, rate, eligible):
    rows = group.loc[group[eligible] > 0, [rate, eligible]]
    denominator = int(rows[eligible].sum())
    counts = rows[rate] * rows[eligible]
    if any(not isfinite(v) or not isclose(v, round(v), rel_tol=1e-12, abs_tol=1e-10)
           for v in counts):
        raise StageAResearchError(f"Invalid implied integer event count: {rate}")
    return denominator, float(counts.sum() / denominator) if denominator else None


def aggregate_metrics(metrics):
    expected = {(split, candidate, symbol) for split in SPLITS
                for candidate in CANDIDATE_IDS for symbol in STAGE_A_SYMBOLS}
    keys = list(metrics[["split", "candidate_id", "symbol"]].itertuples(index=False, name=None))
    if len(keys) != len(expected) or set(keys) != expected:
        raise StageAResearchError("Metric split/candidate/symbol coverage failed")
    output = []
    for split in SPLITS:
        for candidate in CANDIDATE_IDS:
            group = metrics[(metrics.split == split) & (metrics.candidate_id == candidate)]
            row = dict(split=split, candidate_id=candidate,
                       symbols_with_evaluated_days=int((group.evaluated_days > 0).sum()),
                       evaluated_days_total=int(group.evaluated_days.sum()),
                       transitions_total=int(group.transitions.sum()),
                       transition_rate_252_symbol_median=group.transition_rate_per_252.median())
            values = group.persistence_median.dropna()
            for suffix, q in (("median", .5), ("p25", .25), ("p75", .75)):
                row["persistence_symbol_" + suffix] = values.quantile(q, interpolation="linear")
            for prefix, source, horizons in (
                ("false_reversal", "false_reversal_rate", (5, 10, 20)),
                ("directional", "directional_consistency", (5, 10, 20, 60)),
            ):
                for n in horizons:
                    rate, eligible = f"{source}_{n}", f"eligible_{prefix}_{n}"
                    row[f"{prefix}_{n}_symbol_median"] = group[rate].median()
                    row[eligible + "_total"], row[f"{prefix}_{n}_weighted"] = weighted(group, rate, eligible)
            for name in ("mfe_20", "mae_20", "mfe_60", "mae_60"):
                row[name + "_symbol_median"] = group[name + "_median"].median()
            output.append(row)
    return pd.DataFrame(output)


def selection_oos_delta(aggregate):
    selection = aggregate[aggregate.split == "selection"].set_index("candidate_id").drop(columns="split")
    oos = aggregate[aggregate.split == "out_of_sample"].set_index("candidate_id").drop(columns="split")
    return (oos - selection).loc[list(CANDIDATE_IDS)].reset_index()


def aggregate_sensitivity(sensitivity):
    output = []
    keys = ["split", "family", "candidate_a", "candidate_b"]
    for values, group in sensitivity.groupby(keys, sort=True):
        if len(group) != 13 or set(group.symbol) != set(STAGE_A_SYMBOLS):
            raise StageAResearchError("Sensitivity symbol coverage failed")
        row = dict(zip(keys, values), symbols=group.symbol.nunique())
        for name in ("state_agreement", "transition_jaccard_3"):
            for suffix, q in (("median", .5), ("p25", .25), ("p75", .75)):
                row[f"{name}_symbol_{suffix}"] = group[name].dropna().quantile(q, interpolation="linear")
        output.append(row)
    if len(output) != 24:
        raise StageAResearchError("Expected 24 sensitivity groups")
    return pd.DataFrame(output)


def print_scoreboards(coverage, aggregate):
    print("DATA COVERAGE")
    columns = ["symbol", "first_date", "last_date", "rows_before_2005", "selection_rows", "oos_rows"]
    print(pd.DataFrame([dict(symbol=s, **coverage[s]) for s in STAGE_A_SYMBOLS])[columns].to_string(index=False))
    columns = ["candidate_id", "symbols_with_evaluated_days", "transition_rate_252_symbol_median",
               "persistence_symbol_median", "false_reversal_10_weighted", "false_reversal_20_weighted",
               "directional_20_weighted", "directional_60_weighted", "mfe_20_symbol_median", "mae_20_symbol_median"]
    for split, label in zip(SPLITS, ("SELECTION 2005-2019", "OUT-OF-SAMPLE 2020-2026-09-30")):
        print(label)
        print(aggregate.loc[aggregate.split == split, columns].to_string(index=False, float_format=lambda v: f"{v:.4f}"))


def run_stage_a(path):
    destination = output_directory(path)
    frame, coverage = acquire_data()
    destination.mkdir(parents=True, exist_ok=True)
    source = destination / ARTIFACTS[0]
    write_csv(frame, source)
    write_json(data_manifest(coverage, sha256(source)), destination / ARTIFACTS[1])
    tournament = destination / "tournament"
    result = run_tournament(read_csv(source))
    write_outputs(result, tournament)
    check_tournament(tournament, len(frame))
    aggregate = aggregate_metrics(pd.read_csv(tournament / "trend_metrics.csv"))
    write_csv(aggregate, destination / "stage_a_aggregate.csv")
    write_csv(selection_oos_delta(aggregate), destination / "stage_a_selection_oos_delta.csv")
    write_csv(aggregate_sensitivity(pd.read_csv(tournament / "trend_sensitivity.csv")),
              destination / "stage_a_sensitivity_aggregate.csv")
    write_json({name: sha256(destination / name) for name in ARTIFACTS},
               destination / "stage_a_artifact_hashes.json")
    print_scoreboards(coverage, aggregate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        run_stage_a(args.output_dir)
    except (StageADataError, StageAResearchError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
