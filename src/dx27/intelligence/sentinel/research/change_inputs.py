"""Synthetic-only PIT journal; no live provider or production integration."""

from dataclasses import dataclass
from math import log
import numpy as np


@dataclass(frozen=True)
class Capture:
    subject: str
    session: int
    first_seen: int
    close: float
    capture_id: str


@dataclass(frozen=True)
class Snapshot:
    session: int
    returns: tuple[float | None, ...]
    lineage: tuple[tuple[str, ...], ...]


def snapshots(captures, count):
    """Arrival order, never observation-date order; earlier snapshots immutable."""
    arrivals = sorted(captures, key=lambda c: (c.first_seen, c.capture_id))
    latest, cursor, result = {}, 0, []
    for t in range(count):
        while cursor < len(arrivals) and arrivals[cursor].first_seen <= t:
            c = arrivals[cursor]
            if not np.isfinite(c.close) or c.close <= 0:
                raise ValueError("finite positive close required")
            latest[c.subject, c.session] = c
            cursor += 1
        values, ids = [], []
        for subject in ("SPY", "RSP", "QQQ"):
            a, b = latest.get((subject, t - 1)), latest.get((subject, t))
            values.append(log(b.close / a.close) if a and b else None)
            ids.append(tuple(c.capture_id for c in (a, b) if c))
        result.append(Snapshot(t, tuple(values), tuple(ids)))
    return tuple(result)


CASES = (
    "gaussian",
    "student_t5",
    "trend_down",
    "trend_up",
    "vol_up_1.5",
    "vol_up_2",
    "vol_down_1.5",
    "vol_down_2",
    "rsp_up",
    "rsp_down",
    "qqq_up",
    "qqq_down",
    "transient",
    "ramp",
    "joint",
    "missing",
    "delayed",
    "revision",
    "zero_variance",
)


def generate(case, seed, count=1200):
    if case not in CASES:
        raise ValueError("unregistered case")
    rng = np.random.Generator(np.random.PCG64(seed))
    cov = np.full((3, 3), 0.6)
    np.fill_diagonal(cov, 1)
    noise = rng.normal(size=(count, 3)) @ np.linalg.cholesky(cov).T * 0.01
    x = noise.copy()
    if case == "student_t5":
        x = x / np.sqrt(rng.chisquare(5, count)[:, None] / 5) * np.sqrt(3 / 5)
    elif case.startswith("trend_"):
        sign = 1 if case == "trend_down" else -1
        x[:600, :2] += sign * 0.005
        x[600:, :2] -= sign * 0.005
    elif case.startswith("vol_"):
        scale = float(case.split("_")[-1])
        x[600:] *= scale if "_up_" in case else 1 / scale
    elif case.startswith(("rsp_", "qqq_")):
        x[600:, 1 if case.startswith("rsp") else 2] += (
            0.01 if case.endswith("up") else -0.01
        )
    elif case == "transient":
        x[600:605, :2] += 0.03
    elif case == "ramp":
        x[:600, :2] += 0.005
        x[600:700, :2] += np.linspace(0.005, -0.005, 100)[:, None]
        x[700:, :2] -= 0.005
    elif case == "joint":
        x[600:] *= 2
        x[:600, :2] += 0.005
        x[600:, :2] -= 0.005
        x[600:, 2] += 0.01
    elif case == "zero_variance":
        x[:300] = 0
    closes = np.exp(np.log(100) + np.cumsum(x, axis=0))
    captures = []
    for j, subject in enumerate(("SPY", "RSP", "QQQ")):
        captures.append(
            Capture(
                subject,
                -1,
                -1,
                float(np.exp(np.log(100.0))),
                f"{seed}:{case}:{subject}:-1",
            )
        )
        for t in range(count):
            if case == "missing" and j == 0 and 600 <= t <= 604:
                continue
            seen = 605 if case == "delayed" and j == 0 and 600 <= t <= 604 else t
            captures.append(
                Capture(
                    subject,
                    t,
                    seen,
                    float(closes[t, j]),
                    f"{seed}:{case}:{subject}:{t}",
                )
            )
    if case == "revision":
        captures.append(
            Capture(
                "SPY",
                590,
                650,
                float(closes[590, 0] * 1.01),
                f"{seed}:{case}:SPY:590:revision",
            )
        )
    online = snapshots(captures, count)
    truth = x.copy()
    if case == "missing":
        truth[600:606, 0] = np.nan
    return online, truth, tuple(captures)


def subjects(values):
    x = np.array([[np.nan if v is None else v for v in s.returns] for s in values])
    return {
        "trend:SPY": x[:, 0],
        "trend:RSP": x[:, 1],
        "volatility:SPY": x[:, 0],
        "relationship:RSP/SPY": x[:, 1] - x[:, 0],
        "relationship:QQQ/SPY": x[:, 2] - x[:, 0],
    }
