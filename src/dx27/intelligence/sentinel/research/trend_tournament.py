"""Provider-neutral CSV validation, tournament orchestration and artifacts."""

import csv
import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

import pandas as pd

from .trend_metrics import MetricRow, SPLITS, SensitivityRow, evaluate_metrics, evaluate_sensitivity
from .trend_models import CANDIDATES, TrendObservation, candidate_series


STAGE_A_SYMBOLS = ("SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "TLT", "GLD")
REQUIRED_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume")
OUTPUT_FILENAMES = ("trend_states.csv", "trend_metrics.csv", "trend_sensitivity.csv", "trend_tournament_summary.json")
STATE_COLUMNS = ("symbol", "date", "candidate_id", "family", "state", "primary_value",
                 "normalized_score", "sigma_daily", "rsi_14", "is_ready",
                 "source_classification", "sensitivity_only")
METRIC_COLUMNS = (
    "split", "symbol", "candidate_id", "family", "evaluated_days", "transitions", "transition_rate_per_252",
    "persistence_count", "persistence_mean", "persistence_median", "persistence_p25", "persistence_p75",
    "eligible_false_reversal_5", "false_reversal_rate_5", "eligible_false_reversal_10", "false_reversal_rate_10",
    "eligible_false_reversal_20", "false_reversal_rate_20", "eligible_directional_5", "directional_consistency_5",
    "eligible_directional_10", "directional_consistency_10", "eligible_directional_20", "directional_consistency_20",
    "eligible_directional_60", "directional_consistency_60", "mfe_20_mean", "mfe_20_median", "mae_20_mean",
    "mae_20_median", "mfe_60_mean", "mfe_60_median", "mae_60_mean", "mae_60_median",
)
SENSITIVITY_COLUMNS = tuple(SensitivityRow.__dataclass_fields__)


@dataclass(frozen=True)
class DailyBar:
    """One completed daily research bar; adjustment consistency is upstream."""

    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


def _parse_date(value: object) -> date:
    # ISO dates avoid locale-dependent/month-day guessing and time-zone shifts.
    if isinstance(value, datetime):
        if value.time().isoformat() != "00:00:00" or value.tzinfo is not None:
            raise ValueError("Daily dates must be timezone-free dates, not timestamps")
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Date must be an ISO YYYY-MM-DD daily date")
    return date.fromisoformat(value)


def validate_dataframe(frame: pd.DataFrame) -> tuple[DailyBar, ...]:
    """Reject malformed rows; sort only, with no adjustment or gap filling."""
    if not frame.columns.is_unique or any(column not in frame.columns for column in REQUIRED_COLUMNS):
        raise ValueError("CSV requires unique symbol,date,open,high,low,close,volume columns")
    if frame.empty:
        raise ValueError("Input must contain completed daily bars")
    bars = []
    seen = set()
    for record in frame.loc[:, list(REQUIRED_COLUMNS)].to_dict("records"):
        symbol = record["symbol"]
        if not isinstance(symbol, str) or not symbol or symbol != symbol.strip() or any(c.isspace() for c in symbol):
            raise ValueError("Symbol must be a nonempty string without whitespace")
        day = _parse_date(record["date"])
        if (symbol, day) in seen:
            raise ValueError(f"Duplicate symbol/date: {symbol}/{day}")
        seen.add((symbol, day))
        prices = []
        for column in ("open", "high", "low", "close", "volume"):
            value = record[column]
            if isinstance(value, bool):
                raise ValueError(f"Invalid numeric {column}")
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid numeric {column}") from exc
            if not isfinite(numeric) or numeric < 0 or (column != "volume" and numeric == 0):
                raise ValueError(f"{column} must be finite and {'nonnegative' if column == 'volume' else 'positive'}")
            prices.append(numeric)
        opening, high, low, close, volume = prices
        if high < max(opening, close, low) or low > min(opening, close, high):
            raise ValueError("Invalid OHLC high/low ordering")
        bars.append(DailyBar(symbol, day, opening, high, low, close, volume))
    return tuple(sorted(bars, key=lambda bar: (bar.symbol, bar.date)))


def read_csv(path: Path | str) -> pd.DataFrame:
    # Preserve symbols such as "NA" rather than treating them as missing data.
    # csv.reader also catches duplicate headers before pandas can rename them.
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        headers = next(csv.reader(handle), [])
    if len(headers) != len(set(headers)):
        raise ValueError("CSV headers must be unique")
    return pd.read_csv(path, dtype={"symbol": str, "date": str}, keep_default_na=False)


@dataclass(frozen=True)
class TournamentResult:
    observations: tuple[TrendObservation, ...]
    metrics: tuple[MetricRow, ...]
    sensitivity: tuple[SensitivityRow, ...]
    input_symbols: tuple[str, ...]
    input_min_date: date
    input_max_date: date
    input_rows: int
    evaluated_input_rows: int
    input_metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_metadata", MappingProxyType(dict(self.input_metadata)))


def run_tournament(
    frame: pd.DataFrame, symbols: Sequence[str] | None = None,
    *, input_metadata: Mapping[str, str] | None = None,
) -> TournamentResult:
    """Validate ALL rows, then evaluate the explicit universe independently.

    Default requires all Stage-A symbols. An explicit subset never silently
    drops a requested symbol. Extra input symbols are recorded as metadata.
    """
    bars = validate_dataframe(frame)
    input_symbols = tuple(sorted({bar.symbol for bar in bars}))
    expected = tuple(symbols) if symbols is not None else STAGE_A_SYMBOLS
    if not expected or len(expected) != len(set(expected)) or any(
        not isinstance(s, str) or not s or s != s.strip() or any(c.isspace() for c in s) for s in expected
    ):
        raise ValueError("Requested symbols must be unique nonempty symbols")
    missing = sorted(set(expected) - set(input_symbols))
    if missing:
        raise ValueError("Missing requested symbols: " + ", ".join(missing))
    observations, metrics, sensitivity = [], [], []
    evaluated_rows = 0
    # Compute all historical states first; only then give prices to evaluators.
    per_symbol = {}
    for symbol in sorted(expected):
        selected = [bar for bar in bars if bar.symbol == symbol]
        evaluated_rows += len(selected)
        closes = tuple(bar.close for bar in selected)
        states = candidate_series(symbol, tuple(bar.date for bar in selected), closes)
        observations.extend(states)
        per_symbol[symbol] = (closes, {c.candidate_id: tuple(o for o in states if o.candidate_id == c.candidate_id)
                                      for c in CANDIDATES})
    for symbol, (closes, series) in per_symbol.items():
        for split in SPLITS:
            metrics.extend(evaluate_metrics(series[c.candidate_id], closes, split) for c in CANDIDATES)
            sensitivity.extend(evaluate_sensitivity(series, split))
    return TournamentResult(
        tuple(sorted(observations, key=lambda o: (o.symbol, o.candidate_id, o.date))),
        tuple(sorted(metrics, key=lambda r: (r.split, r.symbol, r.candidate_id))),
        tuple(sorted(sensitivity, key=lambda r: (r.split, r.symbol, r.family, r.candidate_a, r.candidate_b))),
        input_symbols, min(bar.date for bar in bars), max(bar.date for bar in bars), len(bars), evaluated_rows,
        input_metadata or {},
    )


def summary(result: TournamentResult) -> dict:
    """Canonical deterministic metadata, with component-level attribution."""
    return {
        "research_id": "dx27.trend_tournament.v0.1",
        "schema_version": 1,
        "input_symbols": list(result.input_symbols),
        "evaluated_symbols": sorted({o.symbol for o in result.observations}),
        "input_min_date": result.input_min_date.isoformat(),
        "input_max_date": result.input_max_date.isoformat(),
        "input_metadata": dict(result.input_metadata),
        "price_adjustment": "Input provider responsibility; prices unchanged",
        "splits": {s.name: {"start": s.start.isoformat(), "end": s.end.isoformat(),
                            "classification": "DX27_RESEARCH_PROTOCOL"} for s in SPLITS},
        "candidate_ids": [c.candidate_id for c in CANDIDATES],
        "parameter_definitions": {c.candidate_id: asdict(c) for c in CANDIDATES},
        "formula_source_classifications": {
            "lean_ema": {"classification": "LEAN_VERIFIED", "source": "QuantConnect LEAN Indicators/ExponentialMovingAverage.cs and Tests/Indicators/ExponentialMovingAverageTests.cs", "definition": "SMA seed after period samples; alpha=2/(period+1)"},
            "lean_ema_cross": {"classification": "LEAN_VERIFIED", "source": "QuantConnect LEAN Algorithm.Framework/Alphas/EmaCrossAlphaModel", "definition": "Daily EMA12-EMA26 directional state only"},
            "ewmac": {"classification": "QC_RESEARCH_REPRODUCTION", "source": "QuantConnect Research 16001: Combined Carry and Trend", "definition": "Independent EMA_fast-EMA_slow; source spans 16/64,32/128,64/256"},
            "ewmac_8_32": {"classification": "DX27_RESEARCH_DEFINITION", "definition": "Sensitivity-only span pair"},
            "ewmac_normalization": {"classification": "DX27_RESEARCH_DEFINITION", "definition": "EWMAC/(close*sigma_daily), not an exact Carver forecast; no annualization, cap or scalar"},
            "tsmom_evidence": {"classification": "ACADEMIC", "source": "Moskowitz, Ooi, Pedersen (2012), Time series momentum, JFE 104(2), 228-250; DOI 10.1016/j.jfineco.2011.11.003", "definition": "Own-return persistence over approximately 1–12 months in 58 studied liquid futures/forward instruments"},
            "tsmom_horizons": {"classification": "DX27_RESEARCH_DEFINITION", "definition": "Daily translations 21/63/126/252; close_t/close_(t-h)-1 determines state"},
            "tsmom_normalization": {"classification": "DX27_RESEARCH_DEFINITION", "definition": "raw_return/(sigma_daily*sqrt(h)), diagnostic only"},
            "metrics": {"classification": "DX27_RESEARCH_DEFINITION", "definition": "State/event behavior, not trading PnL"},
        },
        "sigma_definition": {"classification": "QC_RESEARCH_REPRODUCTION", "source": "QuantConnect Research 15875: Futures Fast Trend Following, with Trend Strength", "returns": "simple close_t/close_(t-1)-1", "span": 32, "min_periods": 32, "adjust": True, "bias": False, "epsilon_floor": False},
        "rsi_definition": {"classification": "LEAN_VERIFIED", "source": "QuantConnect LEAN Indicators/RelativeStrengthIndex.cs", "period": 14, "moving_average": "Wilder", "warmup_price_bars": 15, "seed": "SMA of first 14 gain/loss deltas", "zero_loss_check": "round(avg_loss,10)==0 => 100", "diagnostic_only": True},
        "evaluation_definitions": {"transition_matching_tolerance_observed_bars": 3, "transition_matching": "Ascending A; nearest unused B; earlier B breaks ties", "false_reversal_observations": "next N non-None states; NEUTRAL included", "forward_windows": "within dataset and split", "boundary_transition": "immediately preceding historical state retained", "persistence_quartiles": "pandas linear sample quantiles"},
        "row_counts": {"input": result.input_rows, "evaluated_input": result.evaluated_input_rows,
                       "trend_states": len(result.observations), "trend_metrics": len(result.metrics),
                       "trend_sensitivity": len(result.sensitivity)},
        "output_filenames": list(OUTPUT_FILENAMES),
        "winner_selected": False,
        "production_trend_detector_created": False,
    }


def _csv_text(columns: Sequence[str], rows: Sequence[Mapping]) -> str:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: ("true" if value else "false") if isinstance(value, bool) else value
                         for key, value in row.items()})
    return handle.getvalue()


def write_outputs(result: TournamentResult, output_dir: Path | str) -> None:
    """Write only to the caller's explicit destination; canonical UTF-8 files."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    states = []
    for observation in result.observations:
        row = {name: getattr(observation, name) for name in STATE_COLUMNS}
        row["date"] = observation.date.isoformat()
        row["state"] = observation.state.name if observation.state is not None else None
        states.append(row)
    artifacts = (
        _csv_text(STATE_COLUMNS, states),
        _csv_text(METRIC_COLUMNS, [r.as_dict() for r in result.metrics]),
        _csv_text(SENSITIVITY_COLUMNS, [asdict(r) for r in result.sensitivity]),
        json.dumps(summary(result), sort_keys=True, indent=2, allow_nan=False) + "\n",
    )
    for filename, contents in zip(OUTPUT_FILENAMES, artifacts):
        (directory / filename).write_text(contents, encoding="utf-8")


def csv_metadata(path: Path) -> dict[str, str]:
    """Record input bytes without an absolute path or runtime timestamp."""
    return {"format": "csv", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "completed_daily_bars": "Input contract", "adjustment_semantics": "Provider-supplied; unspecified in CSV"}
