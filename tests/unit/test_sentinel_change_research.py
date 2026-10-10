import numpy as np
import pytest
from dx27.intelligence.sentinel.research.change_inputs import (
    generate,
    snapshots,
    subjects,
    Capture,
)
from dx27.intelligence.sentinel.research.change_detection import (
    replay,
    METHODS,
    fixed_statistic,
)
from dx27.intelligence.sentinel.research.change_scoring import (
    targets,
    match,
    metrics,
    session_statistics,
    paired_interval,
    block_indices,
)


@pytest.mark.parametrize("method", METHODS)
def test_future_and_prefix_causality(method):
    x = np.random.default_rng(7).normal(0, 0.01, 800)
    full = replay(x, "trend", method)
    changed = x.copy()
    changed[650:] += 1
    assert replay(changed, "trend", method)[:650] == full[:650]
    assert replay(x[:650], "trend", method) == full[:650]


def test_delay_revision_journal_retains_original_cutoff():
    base, _, captures = generate("gaussian", 62700)
    late = Capture("SPY", 590, 650, 120.0, "late-revision")
    revised = snapshots((*captures, late), 1200)
    assert revised[:650] == base[:650]
    assert revised[650].history_updates
    assert [u.session for u in revised[650].history_updates] == [590, 591]
    assert all(a.returns == b.returns for a, b in zip(revised, base))
    assert revised != base  # current returns stable, later history/provenance revised
    delayed, _, events = generate("delayed", 62700)
    assert all(delayed[t].returns[0] is None for t in range(600, 605))
    assert any(e.first_seen == 605 and e.session == 600 for e in events)


def test_missing_reset_and_fresh_warmup():
    x = np.random.default_rng(7).normal(0, 0.01, 1000)
    x[600] = np.nan
    for method in METHODS:
        rows = replay(x, "trend", method)
        assert not rows[600].available and rows[600].reset == "GAP"
        assert not any(d.available or d.alarm for d in rows[601:853])
        assert (
            rows[853].available
            if method != "EWMAC_64_256_RESEARCH_ONLY"
            else not rows[853].available
        )


def test_independent_label_matching_and_abstention_denominator():
    from dx27.intelligence.sentinel.research.change_detection import Decision

    decisions = [
        Decision(i, False, "MISSING", None, 0, 0, False, None) for i in range(30)
    ]
    decisions[9] = Decision(
        9, True, "OK", None, 1, 1, False, None
    )  # early alarm cannot receive credit
    decisions[12] = Decision(12, True, "OK", None, 1, 1, False, None)
    valid = np.ones(30, dtype=bool)
    labels = ((10, 1), (20, 1))
    alarms, matches = match(labels, decisions, valid)
    assert matches == ((10, 12, 1),)
    stats, delays, _ = session_statistics(labels, decisions, valid, 1)
    m = metrics(stats, delays)
    assert (
        m["recall"] == 0.5
        and m["precision"] == 0.5
        and m["missed"] == 1
        and m["scorable_sessions"] == 30
    )


def test_zero_sigma_unscorable_and_empty_precision():
    valid, labels = targets(np.zeros(400), "trend")
    assert not valid.any() and not labels
    m = metrics(np.zeros((400, 6)), [])
    assert m["precision"] is None and m["recall"] is None


def test_frozen_statistics_have_disjoint_normalization_windows():
    x = np.arange(1.0, 101.0)
    assert fixed_statistic(x, "trend")[60] == pytest.approx(
        np.mean(x[41:61]) / (np.std(x[21:41], ddof=1) / np.sqrt(20))
    )
    assert fixed_statistic(x, "relationship")[60] == pytest.approx(
        (np.mean(x[56:61]) - np.mean(x[36:56]))
        / (np.std(x[36:56], ddof=1) / np.sqrt(5))
    )


def test_joint_paired_identical_statistics_bootstrap_zero():
    a = np.random.default_rng(1).integers(0, 2, (100, 6)).astype(float)
    assert paired_interval(a, a, block_indices(100)) == [0.0, 0.0]


def test_seed_reproduction_and_no_participation_proxy():
    a, _, _ = generate("rsp_up", 62800)
    b, _, _ = generate("rsp_up", 62800)
    assert a == b and all("participation" not in k for k in subjects(a))


def test_persistence_rearm_and_raw_cooldown(monkeypatch):
    from dx27.intelligence.sentinel.research import change_detection as module

    x = np.random.default_rng(7).normal(0, 0.01, 280)
    statistic = np.zeros(280)
    statistic[253:255] = 3
    statistic[255:257] = -3
    statistic[258:266] = -3
    monkeypatch.setattr(module, "fixed_statistic", lambda x, family: statistic)
    rows = module.replay(x, "trend", "FIXED_THRESHOLD_PERSISTENCE_2")
    assert rows[254].alarm == 1
    assert rows[256].raw_alarm == 0  # opposite trigger side does not rearm
    assert rows[259].raw_alarm == -1 and rows[259].suppressed and rows[259].alarm == 0
    assert rows[260].raw_alarm == 0  # suppressed trigger still disarms until nontrigger


def test_cusum_score_excludes_current_and_resets_suppressed_trigger():
    x = np.tile([-0.01, 0.01], 200).astype(float)
    x[252] = 0.2
    x[253] = -0.2
    rows = replay(x, "trend", "CAUSAL_CUSUM_K05_H5")
    assert rows[252].statistic == pytest.approx(
        (x[252] - np.mean(x[:252])) / np.std(x[:252], ddof=1)
    )
    assert rows[252].alarm == 1 and rows[252].reset == "RAW_TRIGGER"
    assert (
        rows[253].raw_alarm == -1
        and rows[253].suppressed
        and rows[253].reset == "RAW_TRIGGER"
    )


def test_vectorized_labels_against_independent_scalar_oracle():
    x = np.random.default_rng(627).normal(0, 0.01, 900)
    x[500:] += 0.02
    for family, h in [("trend", 40), ("volatility", 10), ("relationship", 20)]:
        valid, labels = targets(x, family)
        expected = []
        last = -10000
        for t in range(252, len(x) - h):
            past = x[t - 19 : t + 1]
            future = x[t + 1 : t + h + 1]
            sigma = np.std(past, ddof=1)
            direction = 0
            if family == "trend":
                means = [np.mean(past), np.mean(future[:20]), np.mean(future[20:])]
                if np.sign(means[1]) == np.sign(means[2]) == -np.sign(means[0]) and min(
                    map(abs, means)
                ) >= sigma / np.sqrt(20):
                    direction = int(np.sign(means[1]))
            elif family == "volatility":
                ratios = [
                    np.std(future[:5], ddof=1) / sigma,
                    np.std(future[5:], ddof=1) / sigma,
                ]
                direction = (
                    1 if min(ratios) >= 1.5 else -1 if max(ratios) <= 2 / 3 else 0
                )
            else:
                d = [
                    np.mean(future[:10]) - np.mean(past),
                    np.mean(future[10:]) - np.mean(past),
                ]
                direction = (
                    1
                    if min(d) >= 2 * sigma / np.sqrt(10)
                    else -1 if max(d) <= -2 * sigma / np.sqrt(10) else 0
                )
            if direction and t - last > h:
                expected.append((t, direction))
                last = t
        assert labels == tuple(expected)


def test_ewmac_matches_archived_candidate_on_same_prices():
    from datetime import date, timedelta
    from dx27.intelligence.sentinel.research.trend_models import candidate_series
    from dx27.intelligence.sentinel.research.change_detection import ewmac_states

    x = np.random.default_rng(6).normal(0, 0.01, 400)
    prices = np.r_[100.0, 100 * np.exp(np.cumsum(x))]
    obs = candidate_series(
        "SPY",
        [date(2000, 1, 1) + timedelta(days=i) for i in range(len(prices))],
        prices,
    )
    states = [o.state for o in obs if o.candidate_id == "ewmac_64_256"][1:]
    actual = ewmac_states(x)
    assert all(
        (not np.isfinite(a)) if b is None else int(a) == int(b)
        for a, b in zip(actual, states)
    )


def test_cusum_against_scalar_history_only_oracle():
    x = np.random.default_rng(51).normal(0, 0.01, 900)
    x[400:410] += 0.1
    x[500] = np.nan
    rows = replay(x, "trend", "CAUSAL_CUSUM_K05_H5")
    plus = minus = 0.0
    last = -10000
    for t, d in enumerate(rows):
        history = x[max(0, t - 252) : t]
        if (
            len(history) < 252
            or not np.all(np.isfinite(history))
            or not np.isfinite(x[t])
            or np.std(history, ddof=1) <= 0
        ):
            plus = minus = 0.0
            assert not d.available and d.raw_alarm == 0
            continue
        z = (x[t] - np.mean(history)) / np.std(history, ddof=1)
        plus = max(0.0, plus + z - 0.5)
        minus = max(0.0, minus - z - 0.5)
        raw = (
            (1 if plus > minus else -1 if minus > plus else 0)
            if max(plus, minus) >= 5
            else 0
        )
        if max(plus, minus) >= 5:
            plus = minus = 0.0
        alarm = raw if t - last > 5 else 0
        if alarm:
            last = t
        assert (
            d.statistic == pytest.approx(z) and d.raw_alarm == raw and d.alarm == alarm
        )


def test_moving_block_interval_matches_explicit_resampling_without_rematching():
    from dx27.intelligence.sentinel.research.change_scoring import _f1

    rng = np.random.default_rng(1)
    a = rng.integers(0, 2, (101, 6)).astype(float)
    b = rng.integers(0, 2, (101, 6)).astype(float)
    starts = block_indices(101)
    totals_a = []
    totals_b = []
    for draw in starts:
        indices = np.concatenate([np.arange(s, s + 40) for s in draw])[:101]
        totals_a.append(a[indices].sum(axis=0))
        totals_b.append(b[indices].sum(axis=0))
    expected = np.quantile(
        _f1(np.asarray(totals_a)) - _f1(np.asarray(totals_b)), [0.025, 0.975]
    )
    assert paired_interval(a, b, starts) == pytest.approx(expected)


def test_inputs_future_arrivals_and_duplicate_revision_order_are_causal():
    a, _, captures = generate("gaussian", 62700)
    evil = Capture("SPY", 590, 1201, 1.0, "after-last-cutoff")
    assert snapshots((*captures, evil), 1200) == a
    assert snapshots(tuple(reversed(captures)), 1200) == a


def test_protocol_lock_and_gates_are_verified_before_output_creation():
    from pathlib import Path
    from dx27.intelligence.sentinel.research.change_synthetic import verify_protocol

    p, lock = verify_protocol(Path(__file__).resolve().parents[2])
    assert not p["production_enabled"] and not p["confirmation_started"]
    assert p["real_validation"] == "BLOCKED_DATA"
    assert (
        lock["protocol_file_sha256"]
        == "ccf815ce7837daedb9c0663a5587943b99d2c48928bff80751befaec2c55e92f"
    )


def test_gzip_evidence_bytes_reproducible(tmp_path):
    from dx27.intelligence.sentinel.research.change_synthetic import gzip_lines
    import gzip

    for name in ("a.gz", "b.gz"):
        with gzip_lines(tmp_path / name) as stream:
            stream.write(b"example synthetic evidence\n")
    assert (tmp_path / "a.gz").read_bytes() == (tmp_path / "b.gz").read_bytes()
    assert (
        gzip.decompress((tmp_path / "a.gz").read_bytes())
        == b"example synthetic evidence\n"
    )


def test_archive_rejects_tampered_execution_before_creating_destination(tmp_path):
    import json
    from dx27.intelligence.sentinel.research.change_archive import archive

    src = tmp_path / "execution"
    src.mkdir()
    dst = tmp_path / "archive"
    (src / "report.json").write_text("{}")
    (src / "artifact_hashes.json").write_text(json.dumps({"report.json": "bad-hash"}))
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        archive(src, dst)
    assert not dst.exists()


def test_generated_zero_variance_has_no_roundoff_pseudo_return():
    online, _, _ = generate("zero_variance", 62700)
    assert all(s.returns == (0.0, 0.0, 0.0) for s in online[:300])
    for subject, x in subjects(online).items():
        for method in METHODS:
            decisions = replay(x, subject.split(":")[0], method)
            assert not any(d.available or d.alarm for d in decisions[:300])


def test_nonzero_constant_history_is_exact_zero_variance_without_epsilon():
    from dx27.intelligence.sentinel.research.change_detection import rolling

    x = np.full(400, 0.1)
    assert np.all(rolling(x, 252)[1][251:] == 0.0)
    for method in (
        "NO_CHANGE",
        "FIXED_CAUSAL_THRESHOLD_V1",
        "FIXED_THRESHOLD_PERSISTENCE_2",
        "CAUSAL_CUSUM_K05_H5",
    ):
        rows = replay(x, "trend", method)
        assert not any(d.available or d.alarm for d in rows)


def asof_close_oracle(captures, cutoff):
    """Independent cutoff query; never uses Snapshot.history_updates or replay helpers."""
    from math import log

    latest = {}
    for c in captures:
        key = (c.subject, c.session)
        if c.first_seen <= cutoff and (
            key not in latest
            or (c.first_seen, c.capture_id)
            > (latest[key].first_seen, latest[key].capture_id)
        ):
            latest[key] = c
    values = []
    lineage = []
    for t in range(cutoff + 1):
        row = []
        ids = []
        for subject in ("SPY", "RSP", "QQQ"):
            a = latest.get((subject, t - 1))
            b = latest.get((subject, t))
            row.append(log(b.close / a.close) if a and b else np.nan)
            ids.append(tuple(c.capture_id for c in (a, b) if c))
        values.append(row)
        lineage.append(ids)
    return np.asarray(values), lineage


@pytest.mark.parametrize(
    "subject",
    ["trend:SPY", "volatility:SPY", "relationship:RSP/SPY", "relationship:QQQ/SPY"],
)
def test_registered_revision_features_against_asof_oracle(subject):
    from dx27.intelligence.sentinel.research.change_inputs import history_changes

    online, _, captures = generate("revision", 62700)
    x = subjects(online)[subject]
    updates = history_changes(online, subject)
    family = subject.split(":")[0]
    base = replay(x, family, "CAUSAL_CUSUM_K05_H5")
    revised = replay(x, family, "CAUSAL_CUSUM_K05_H5", updates)
    assert revised[:650] == base[:650]
    assert revised[650].history_vintage == 650
    assert revised[650].statistic != base[650].statistic
    assert [u.session for u in updates] == [590, 591]
    revision_id = next(
        c.capture_id for c in captures if c.first_seen == 650 and c.session == 590
    )
    assert all(revision_id in u.lineage for u in updates)
    for t in (649, 650, 651, 700, 842, 843, 844, 900):
        values, _ = asof_close_oracle(captures, t)
        series = (
            values[:, 0]
            if family != "relationship"
            else values[:, 1 if subject.startswith("relationship:RSP") else 2]
            - values[:, 0]
        )
        if family == "volatility":
            series = np.log(np.abs(series))
        history = series[t - 252 : t]
        expected = (series[t] - np.mean(history)) / np.std(history, ddof=1)
        assert revised[t].statistic == pytest.approx(expected, rel=1e-12, abs=1e-12)
    # After both corrected returns leave the 252-session window, the score agrees,
    # but retained accumulators/cooldown are deliberately not rewound or discarded.
    assert revised[844].statistic == base[844].statistic


def test_revision_cusum_retains_original_state_and_never_retrocredits():
    from dx27.intelligence.sentinel.research.change_inputs import history_changes
    from dx27.intelligence.sentinel.research.change_detection import Decision

    online, _, captures = generate("revision", 62800)
    x = subjects(online)["trend:SPY"]
    updates = history_changes(online, "trend:SPY")
    actual = replay(x, "trend", "CAUSAL_CUSUM_K05_H5", updates)
    plus = minus = 0.0
    last = -10000
    for t in range(252, len(x)):
        values, _ = asof_close_oracle(captures, t)
        history = values[t - 252 : t, 0]
        z = (values[t, 0] - np.mean(history)) / np.std(history, ddof=1)
        plus = max(0.0, plus + z - 0.5)
        minus = max(0.0, minus - z - 0.5)
        raw = (
            (1 if plus > minus else -1 if minus > plus else 0)
            if max(plus, minus) >= 5
            else 0
        )
        if max(plus, minus) >= 5:
            plus = minus = 0.0
        alarm = raw if t - last > 5 else 0
        if alarm:
            last = t
        assert (
            actual[t].statistic == pytest.approx(z)
            and actual[t].raw_alarm == raw
            and actual[t].alarm == alarm
        )
    rows = [Decision(i, True, "OK", None, 0, 0, False, None) for i in range(700)]
    rows[650] = Decision(650, True, "OK", None, 1, 1, False, None, 650)
    assert match(((590, 1),), rows, np.ones(700, dtype=bool))[1] == ()


def test_revision_ewmac_is_measured_from_current_vintage_not_replayed_alarms():
    from dx27.intelligence.sentinel.research.change_inputs import history_changes
    from dx27.intelligence.sentinel.research.trend_models import lean_ema, qc_ewmstd

    online, _, captures = generate("revision", 62700)
    x = subjects(online)["trend:SPY"]
    u = history_changes(online, "trend:SPY")
    base = replay(x, "trend", "EWMAC_64_256_RESEARCH_ONLY")
    actual = replay(x, "trend", "EWMAC_64_256_RESEARCH_ONLY", u)
    assert actual[:650] == base[:650]
    for t in (650, 651, 700):
        values, _ = asof_close_oracle(captures, t)
        prices = np.r_[100.0, 100 * np.exp(np.cumsum(values[:, 0]))]
        score = (lean_ema(prices, 64)[-1] - lean_ema(prices, 256)[-1]) / (
            prices[-1] * qc_ewmstd(prices)[-1]
        )
        assert actual[t].statistic == float(np.sign(score))
        assert actual[t].history_vintage == 650


@pytest.mark.parametrize(
    "family,subject,observation",
    [
        ("trend", "trend:SPY", 620),
        ("volatility", "volatility:SPY", 640),
        ("relationship", "relationship:RSP/SPY", 630),
    ],
)
def test_threshold_features_use_recent_revisions_in_normalization(
    family, subject, observation
):
    from dx27.intelligence.sentinel.research.change_inputs import history_changes

    online, _, captures = generate("gaussian", 62700)
    original = next(
        c for c in captures if c.subject == "SPY" and c.session == observation
    )
    corrected = Capture(
        "SPY", observation, 650, original.close * 1.1, "recent-correction"
    )
    revised = snapshots((*captures, corrected), 1200)
    updates = history_changes(revised, subject)
    x = subjects(revised)[subject]
    for method in (
        "FIXED_CAUSAL_THRESHOLD_V1",
        "FIXED_THRESHOLD_PERSISTENCE_2",
        "NO_CHANGE",
    ):
        a = replay(x, family, method)
        b = replay(x, family, method, updates)
        assert b[:650] == a[:650]
        values, _ = asof_close_oracle((*captures, corrected), 650)
        series = (
            values[:, 0] if family != "relationship" else values[:, 1] - values[:, 0]
        )
        if family == "trend":
            expected = np.mean(series[-20:]) / (
                np.std(series[-40:-20], ddof=1) / np.sqrt(20)
            )
        elif family == "volatility":
            expected = np.std(series[-5:], ddof=1) / np.std(series[-20:], ddof=1)
        else:
            expected = (np.mean(series[-5:]) - np.mean(series[-25:-5])) / (
                np.std(series[-25:-5], ddof=1) / np.sqrt(5)
            )
        assert (
            b[650].statistic == pytest.approx(expected)
            and b[650].statistic != a[650].statistic
        )


def test_delayed_history_visible_later_but_does_not_repair_original_eligibility():
    from dx27.intelligence.sentinel.research.change_inputs import history_changes

    online, _, captures = generate("delayed", 62700)
    updates = history_changes(online, "trend:SPY")
    assert len(updates) == 5 and all(u.cutoff == 605 for u in updates)
    original = online[600]
    assert original.returns[0] is None
    values, ids = asof_close_oracle(captures, 605)
    assert updates[0].value == values[600, 0] and updates[0].lineage == ids[600][0]
    actual = replay(
        subjects(online)["trend:SPY"], "trend", "CAUSAL_CUSUM_K05_H5", updates
    )
    assert not any(d.available or d.alarm for d in actual[600:857])
    assert online[600] == original
