"""Frozen 6B-2J-A research candidates. Alarms are not DetectionResult objects."""

from dataclasses import dataclass
import numpy as np
from .trend_models import lean_ema, qc_ewmstd

METHODS = (
    "NO_CHANGE",
    "FIXED_CAUSAL_THRESHOLD_V1",
    "EWMAC_64_256_RESEARCH_ONLY",
    "FIXED_THRESHOLD_PERSISTENCE_2",
    "CAUSAL_CUSUM_K05_H5",
)


@dataclass(frozen=True)
class Decision:
    session: int
    available: bool
    reason: str
    statistic: float | None
    raw_alarm: int
    alarm: int
    suppressed: bool
    reset: str | None
    history_vintage: int | None = None


def rolling(x, width):
    """Current-ending rolling mean/sample std; never use a future sample."""
    x = np.asarray(x, dtype=float)
    mean = np.full(len(x), np.nan)
    std = mean.copy()
    if len(x) >= width:
        windows = np.lib.stride_tricks.sliding_window_view(x, width)
        mean[width - 1 :] = np.mean(windows, axis=1)
        std[width - 1 :] = np.std(windows, axis=1, ddof=1)
        # Exact constant samples have zero variance even if summation rounds the mean.
        # This is an identity check, not an epsilon floor or volatility imputation.
        constant = np.all(windows == windows[:, :1], axis=1)
        std[width - 1 :][constant] = 0.0
    return mean, std


def shifted(x, n):
    out = np.full(len(x), np.nan)
    if len(x) > n:
        out[n:] = x[:-n]
    return out


def fixed_statistic(x, family):
    m20, s20 = rolling(x, 20)
    if family == "trend":
        numerator, denominator = m20, shifted(s20, 20) / np.sqrt(20)
    elif family == "relationship":
        numerator, denominator = rolling(x, 5)[0] - shifted(m20, 5), shifted(
            s20, 5
        ) / np.sqrt(5)
    elif family == "volatility":
        numerator, denominator = rolling(x, 5)[1], s20
    else:
        raise ValueError("unregistered family")
    out = np.full(len(x), np.nan)
    np.divide(numerator, denominator, out=out, where=denominator > 0)
    return out


def side(value, family):
    if family == "volatility":
        return 1 if value >= 1.5 else -1 if value <= 2 / 3 else 0
    return 1 if value >= 2 else -1 if value <= -2 else 0


def ewmac_states(x):
    """Reuse archived price EMA and volatility method, restart after input gaps."""
    out = np.full(len(x), np.nan)
    start = 0
    for end in range(len(x) + 1):
        if end == len(x) or not np.isfinite(x[end]):
            segment = x[start:end]
            if len(segment):
                prices = np.r_[100.0, 100.0 * np.exp(np.cumsum(segment))]
                fast, slow, sigma = (
                    lean_ema(prices, 64),
                    lean_ema(prices, 256),
                    qc_ewmstd(prices),
                )
                for i in range(len(segment)):
                    k = i + 1
                    if (
                        fast[k] is not None
                        and slow[k] is not None
                        and sigma[k] is not None
                        and sigma[k] > 0
                    ):
                        out[start + i] = np.sign(
                            (fast[k] - slow[k]) / (prices[k] * sigma[k])
                        )
            start = end + 1
    return out


def measurements(x, family, method):
    stat = fixed_statistic(x, family)
    feature = x.copy()
    if family == "volatility":
        feature[:] = np.nan
        mask = np.isfinite(x) & (x != 0)
        feature[mask] = np.log(np.abs(x[mask]))
    mean = std = None
    if method == "CAUSAL_CUSUM_K05_H5":
        mean, std = rolling(feature, 252)
        mean, std = shifted(mean, 1), shifted(std, 1)
    states = (
        ewmac_states(x)
        if method == "EWMAC_64_256_RESEARCH_ONLY" and family == "trend"
        else None
    )
    return stat, feature, mean, std, states


def asof_measurements(x, family, method, history_updates):
    """Recompute numerical features per vintage, never replay emitted state."""
    base = measurements(x, family, method)
    columns = [None if v is None else v.copy() for v in base]
    vintage = [None] * len(x)
    groups = {}
    for change in history_updates:
        if change.cutoff >= len(x):
            continue
        if change.session < 0 or change.session >= change.cutoff or change.cutoff < 0:
            raise ValueError("historical overlay must precede its arrival cutoff")
        if change.value is not None and not np.isfinite(change.value):
            raise ValueError("finite historical return required")
        if change.cutoff < len(x):
            groups.setdefault(change.cutoff, []).append(change)
    cutoffs = sorted(groups)
    view = x.copy()
    for i, cutoff in enumerate(cutoffs):
        for change in groups[cutoff]:
            view[change.session] = np.nan if change.value is None else change.value
        end = cutoffs[i + 1] if i + 1 < len(cutoffs) else len(x)
        current = measurements(view, family, method)
        for dest, source in zip(columns, current):
            if dest is not None:
                dest[cutoff:end] = source[cutoff:end]
        vintage[cutoff:end] = [cutoff] * (end - cutoff)
    return (*columns, vintage)


def replay(x, family, method, history_updates=()):
    if method not in METHODS:
        raise ValueError("unregistered method")
    x = np.asarray(x, dtype=float)
    stat, feature, mean, std, states, vintage = asof_measurements(
        x, family, method, history_updates
    )
    consecutive = 0
    previous = None
    run = 0
    armed = True
    plus = minus = 0.0
    last_alarm = -10000
    decisions = []
    for t, value in enumerate(x):
        prior_count = consecutive
        consecutive = consecutive + 1 if np.isfinite(value) else 0
        reason = "OK"
        raw = 0
        reset = None
        score = None
        if not np.isfinite(value):
            reason = "MISSING"
            reset = "GAP"
        elif prior_count < 252:
            reason = "WARMUP"
            reset = "WARMUP"
        elif method not in (
            "CAUSAL_CUSUM_K05_H5",
            "EWMAC_64_256_RESEARCH_ONLY",
        ) and not np.isfinite(stat[t]):
            reason = "ZERO_VARIANCE_OR_INVALID_STATISTIC"
            reset = "INVALID"
        if method == "EWMAC_64_256_RESEARCH_ONLY" and family != "trend":
            reason = "COMPARATOR_NOT_APPLICABLE"
            reset = "NOT_APPLICABLE"
        if reason == "OK" and method == "CAUSAL_CUSUM_K05_H5":
            if not np.isfinite(feature[t]) or not np.isfinite(std[t]) or std[t] <= 0:
                reason = "ZERO_VARIANCE_OR_INVALID_FEATURE"
                reset = "INVALID"
            else:
                score = float((feature[t] - mean[t]) / std[t])
                plus = max(0.0, plus + score - 0.5)
                minus = max(0.0, minus - score - 0.5)
                if max(plus, minus) >= 5:
                    raw = 1 if plus > minus else -1 if minus > plus else 0
                    if not raw:
                        reason = "CUSUM_TIE"
                    plus = minus = 0.0
                    reset = "RAW_TRIGGER"
        elif reason == "OK" and method == "EWMAC_64_256_RESEARCH_ONLY":
            if not np.isfinite(states[t]):
                reason = "ARCHIVED_EMA_WARMUP"
                reset = "INVALID"
            else:
                score = float(states[t])
                current = int(score)
                if previous is not None and current != 0 and current != previous:
                    raw = current
                previous = current
        elif reason == "OK":
            score = float(stat[t])
            current = side(score, family)
            if method == "FIXED_CAUSAL_THRESHOLD_V1":
                if previous is not None and current != 0 and current != previous:
                    raw = current
            elif method == "FIXED_THRESHOLD_PERSISTENCE_2":
                if previous is None:
                    run = 1 if current else 0
                elif current == 0:
                    run = 0
                    armed = True
                elif current != previous:
                    run = 1
                else:
                    run += 1
                if previous is not None and current and run == 2 and armed:
                    raw = current
                    armed = False
            previous = current
        if reason != "OK":
            previous = None
            run = 0
            armed = True
            plus = minus = 0.0
        suppressed = bool(raw and t - last_alarm <= 5)
        alarm = 0 if suppressed else raw
        if alarm:
            last_alarm = t
        decisions.append(
            Decision(
                t,
                reason == "OK",
                reason,
                score,
                raw,
                alarm,
                suppressed,
                reset,
                vintage[t],
            )
        )
    return tuple(decisions)
