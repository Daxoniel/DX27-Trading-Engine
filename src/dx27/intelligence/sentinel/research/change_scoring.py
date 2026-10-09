"""Evaluation-only future labels and fixed chronology one-to-one matching."""

import numpy as np
from .change_detection import rolling

HORIZONS = {"trend": 40, "volatility": 10, "relationship": 20}


def targets(x, family):
    x = np.asarray(x, dtype=float)
    n = len(x)
    h = HORIZONS[family]
    valid = np.zeros(n, dtype=bool)
    raw = np.zeros(n, dtype=int)
    mean20, sigma = rolling(x, 20)
    if family == "trend":
        first = np.r_[mean20[20:], np.full(20, np.nan)]
        second = np.r_[mean20[40:], np.full(40, np.nan)]
        valid = (
            np.isfinite(mean20)
            & np.isfinite(sigma)
            & (sigma > 0)
            & np.isfinite(first)
            & np.isfinite(second)
        )
        hit = (
            valid
            & (np.sign(first) == np.sign(second))
            & (np.sign(first) == -np.sign(mean20))
            & (
                np.minimum(np.minimum(abs(mean20), abs(first)), abs(second))
                >= sigma / np.sqrt(20)
            )
        )
        raw[hit] = np.sign(first[hit]).astype(int)
    elif family == "volatility":
        s5 = rolling(x, 5)[1]
        first = np.r_[s5[5:], np.full(5, np.nan)]
        second = np.r_[s5[10:], np.full(10, np.nan)]
        valid = (
            np.isfinite(sigma) & (sigma > 0) & np.isfinite(first) & np.isfinite(second)
        )
        raw[valid & (np.minimum(first, second) >= 1.5 * sigma)] = 1
        raw[valid & (np.maximum(first, second) <= 2 * sigma / 3)] = -1
    elif family == "relationship":
        m10 = rolling(x, 10)[0]
        first = np.r_[m10[10:], np.full(10, np.nan)] - mean20
        second = np.r_[m10[20:], np.full(20, np.nan)] - mean20
        valid = (
            np.isfinite(mean20)
            & np.isfinite(sigma)
            & (sigma > 0)
            & np.isfinite(first)
            & np.isfinite(second)
        )
        raw[valid & (np.minimum(first, second) >= 2 * sigma / np.sqrt(10))] = 1
        raw[valid & (np.maximum(first, second) <= -2 * sigma / np.sqrt(10))] = -1
    else:
        raise ValueError("unregistered family")
    valid[:252] = False
    valid[n - h :] = False
    raw[~valid] = 0
    kept = []
    last = -10000
    for t in np.flatnonzero(raw):
        if t - last > h:
            kept.append((int(t), int(raw[t])))
            last = t
    return valid, tuple(kept)


def match(labels, decisions, valid):
    alarms = [(d.session, d.alarm) for d in decisions if d.alarm and valid[d.session]]
    used = set()
    result = []
    for t, direction in labels:
        for i, (a, adirection) in enumerate(alarms):
            if i not in used and direction == adirection and t <= a <= t + 5:
                used.add(i)
                result.append((t, a, direction))
                break
    return tuple(alarms), tuple(result)


def session_statistics(labels, decisions, valid, direction):
    alarms, matches = match(labels, decisions, valid)
    # TP_alarm, TP_target, FP, FN, available, scorable: distinct time placements.
    stats = np.zeros((len(valid), 6), dtype=float)
    stats[:, 5] = valid
    stats[:, 4] = valid & np.array([d.available for d in decisions])
    matched_alarms = {a for _, a, d in matches if d == direction}
    matched_labels = {t for t, _, d in matches if d == direction}
    for a, d in alarms:
        if d == direction:
            stats[a, 0 if a in matched_alarms else 2] += 1
    for t, d in labels:
        if d == direction:
            stats[t, 1 if t in matched_labels else 3] += 1
    delays = [a - t for t, a, d in matches if d == direction]
    return stats, delays, matches


def metrics(stats, delays):
    ta, tt, fp, fn, available, scored = stats.sum(axis=0)
    precision = ta / (ta + fp) if ta + fp else None
    recall = tt / (tt + fn) if tt + fn else None
    f1 = (
        None
        if precision is None or recall is None
        else (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
    )
    return {
        "labels": int(tt + fn),
        "alarms": int(ta + fp),
        "matched": int(ta),
        "false_alarms": int(fp),
        "missed": int(fn),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "median_delay": float(np.quantile(delays, 0.5)) if delays else None,
        "p90_delay": float(np.quantile(delays, 0.9)) if delays else None,
        "unmatched_per_252": float(fp / scored * 252) if scored else None,
        "availability": float(available / scored) if scored else None,
        "scorable_sessions": int(scored),
    }


def _f1(totals):
    ta, tt, fp, fn = totals[:, :4].T
    precision = np.divide(ta, ta + fp, out=np.zeros_like(ta), where=ta + fp > 0)
    recall = np.divide(tt, tt + fn, out=np.zeros_like(tt), where=tt + fn > 0)
    return np.divide(
        2 * precision * recall,
        precision + recall,
        out=np.zeros_like(ta),
        where=precision + recall > 0,
    )


def block_indices(n):
    # Identical joint calendar block draws for all subjects and paired methods.
    rng = np.random.Generator(np.random.PCG64(627))
    return rng.integers(0, n - 40 + 1, size=(1000, (n + 39) // 40))


def paired_interval(candidate, baseline, starts):
    def totals(stats):
        sums = np.vstack([np.zeros((1, 6)), np.cumsum(stats, axis=0)])
        blocks = sums[40:] - sums[:-40]
        out = blocks[starts].sum(axis=1)
        excess = starts.shape[1] * 40 - len(stats)
        if excess:
            end = starts[:, -1] + 40
            out -= sums[end] - sums[end - excess]
        return out

    differences = _f1(totals(candidate)) - _f1(totals(baseline))
    return [float(v) for v in np.quantile(differences, [0.025, 0.975])]


def verdict(m, uplift, interval):
    if m["labels"] < 30 or any(
        m[k] is None
        for k in (
            "precision",
            "recall",
            "median_delay",
            "p90_delay",
            "availability",
            "f1",
        )
    ):
        return "INSUFFICIENT_EVIDENCE"
    checks = [
        m["precision"] >= 0.6,
        m["recall"] >= 0.6,
        m["median_delay"] <= 3,
        m["p90_delay"] <= 5,
        m["unmatched_per_252"] <= 12,
        m["availability"] >= 0.95,
        uplift >= 0.05,
        interval[0] > 0,
    ]
    return "PASS" if all(checks) else "FAIL"
