"""The public demo contains only reproducible offline synthetic examples."""

import hashlib
import json
import socket
from zipfile import ZipFile

import pytest

from runners.standalone.sentinel_observation_example import (
    ARCHIVE_NAME,
    PUBLIC_FILES,
    generate,
)


def test_public_example_is_offline_synthetic_allowlisted_and_degrades(
    tmp_path, monkeypatch
):
    def no_network(*args, **kwargs):
        pytest.fail("synthetic example attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", no_network)
    output = generate(tmp_path / "demo")
    healthy = json.loads((output / "synthetic-report.json").read_text())
    degraded = json.loads((output / "degraded-synthetic-report.json").read_text())
    assert set(p.name for p in output.iterdir()) == {*PUBLIC_FILES, ARCHIVE_NAME}
    for report in (healthy, degraded):
        assert report["report_kind"] == "SYNTHETIC_DEMO"
        assert report["data_role"] == "SYNTHETIC_FIXTURE_ONLY"
        assert report["real_market_observations"] == 0
        assert report["admission_status"] == "BLOCKED_DATA"
        assert report["production_enabled"] is False
        assert {s["source_id"] for s in report["source_results"]} == {
            "SYNTHETIC_FIXTURE"
        }
    assert healthy["market_now"]["coverage"]["active_required"]["available"] == 13
    assert degraded["latest_fetch_failed_feeds"] == ["spy"]
    assert degraded["freshness_status"] == "DEGRADED_LATEST_FETCH_FAILED"
    spy = next(
        entry["state"]
        for entry in degraded["market_now"]["broad_equity"]
        if entry["sensor_id"] == "spy_return_20"
    )
    assert spy["value"] is None
    assert degraded["market_now"]["coverage"]["active_required"]["available"] < 13
    for prefix in ("", "degraded-"):
        for suffix in ("html", "md"):
            assert (
                "合成"
                in (
                    output / (prefix + "synthetic-market-observation." + suffix)
                ).read_text()
            )
    with ZipFile(output / ARCHIVE_NAME) as archive:
        assert set(archive.namelist()) == set(PUBLIC_FILES)
        assert all(
            "/" not in name and "payload" not in name for name in archive.namelist()
        )
    repeated = generate(tmp_path / "repeated")
    assert (
        hashlib.sha256((output / ARCHIVE_NAME).read_bytes()).digest()
        == hashlib.sha256((repeated / ARCHIVE_NAME).read_bytes()).digest()
    )
    with pytest.raises(FileExistsError):
        generate(output)
