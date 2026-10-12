"""The downloadable forecast example is an offline display stub, not model evidence."""

import hashlib
import json
import math
import socket
from zipfile import ZipFile

import pytest

from runners.standalone.sentinel_forecast_example import (
    ARCHIVE_NAME,
    PUBLIC_FILES,
    generate,
)


def test_public_forecast_example_is_offline_synthetic_allowlisted_and_reproducible(
    tmp_path, monkeypatch
):
    def no_network(*args, **kwargs):
        pytest.fail("synthetic forecast example attempted network access")

    def no_real_model(*args, **kwargs):
        pytest.fail("display example attempted to construct or download a real model")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(
        "dx27.adapters.sentinel.forecast_model.ChronosBackend.__init__", no_real_model
    )
    output = generate(tmp_path / "demo")
    healthy = json.loads((output / "synthetic-report.json").read_text())
    degraded = json.loads((output / "degraded-synthetic-report.json").read_text())

    assert len(PUBLIC_FILES) == 7
    assert set(p.name for p in output.iterdir()) == {*PUBLIC_FILES, ARCHIVE_NAME}
    for report in (healthy, degraded):
        assert report["report_kind"] == "SYNTHETIC_DEMO"
        assert report["data_role"] == "SYNTHETIC_FIXTURE_ONLY"
        assert report["real_market_observations"] == 0
        assert report["production_enabled"] is False
        assert report["admission_status"] == "BLOCKED_DATA"
        assert {s["source_id"] for s in report["source_results"]} == {
            "SYNTHETIC_FIXTURE"
        }
        assert all(
            s["url"].startswith("https://synthetic.example.invalid/")
            for s in report["source_results"]
        )
        forecast = report["experimental_forecast"]
        assert forecast["report_kind"] == "SYNTHETIC_DEMO"
        assert forecast["real_market_observations"] == 0
        assert forecast["model_id"] == "SYNTHETIC_DISPLAY_STUB_NOT_CHRONOS2"
        assert forecast["model_revision"] == "synthetic-fixture-v1"
        assert forecast["model_source_url"] is None
        assert "model_weight_sha256" not in forecast
        assert "model_weight_sha256_expected" not in forecast
        assert forecast["inference_config"]["device"] == "offline_display_stub"
        assert forecast["origin_session"] == "2026-10-09"
        assert forecast["target_session"] == "2026-10-16"
        assert forecast["horizon_sessions"] == 5
        assert forecast["calibration_status"] == "NOT_VALIDATED"
        assert forecast["predictive_effectiveness"] == "NOT_TESTED"
        assert forecast["production_enabled"] is False
        assert forecast["admission_status"] == "BLOCKED_DATA"

    normal = healthy["experimental_forecast"]
    failed = degraded["experimental_forecast"]
    assert normal["status"] == "AVAILABLE_EXPERIMENTAL"
    assert len(normal["predictions"]) == 7
    assert all(p["status"] == "AVAILABLE" for p in normal["predictions"])
    assert failed["status"] == "PARTIAL"
    assert len(failed["predictions"]) == 7
    assert {
        p["target_id"] for p in failed["predictions"] if p["status"] == "AVAILABLE"
    } == {"rsp_forward_return_5", "qqq_forward_return_5", "iwm_forward_return_5"}
    assert degraded["latest_fetch_failed_feeds"] == ["spy"]
    unavailable = [p for p in failed["predictions"] if p["status"] != "AVAILABLE"]
    assert all("LATEST_FETCH_FAILED" in p["reason"] for p in unavailable)
    assert all("q50_return" not in p for p in unavailable)

    # Check an observation against the fixed formula, not a market price source.
    spy = next(
        e["state"]
        for e in healthy["market_now"]["broad_equity"]
        if e["sensor_id"] == "spy_return_20"
    )
    expected_synthetic_log_return = 0.001 * 20 + 0.003 * (math.sin(252) - math.sin(232))
    assert spy["value"]["amount"] == pytest.approx(expected_synthetic_log_return)
    for prefix in ("", "degraded-"):
        for suffix in ("html", "md"):
            text = (
                output / (prefix + "synthetic-market-forecast." + suffix)
            ).read_text()
            assert "合成" in text
            assert "SYNTHETIC_DISPLAY_STUB_NOT_CHRONOS2" in text

    with ZipFile(output / ARCHIVE_NAME) as archive:
        assert set(archive.namelist()) == set(PUBLIC_FILES)
        assert all("/" not in name and "\\" not in name for name in archive.namelist())
        assert all(
            "capture" not in name and "payload" not in name
            for name in archive.namelist()
        )
        assert all(
            archive.read(name) == (output / name).read_bytes() for name in PUBLIC_FILES
        )

    repeated = generate(tmp_path / "repeated")
    assert (
        hashlib.sha256((output / ARCHIVE_NAME).read_bytes()).digest()
        == hashlib.sha256((repeated / ARCHIVE_NAME).read_bytes()).digest()
    )
    with pytest.raises(FileExistsError):
        generate(output)
