import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from dx27.adapters.intraday import data


def csv_file(tmp_path, rows):
    path = tmp_path / "minute.csv"
    path.write_text("symbol,timestamp,open,high,low,close,volume\n" + "\n".join(rows) + "\n")
    return path


def test_import_sorts_symbols_and_normalizes_offsets_without_combining_duplicates(tmp_path):
    path = csv_file(tmp_path, ["SPY,2025-11-26T09:30:00-05:00,100,101,99,100,500",
                               "QQQ,2025-11-26T14:30:00Z,100,101,99,100,500"])
    dataset = data.load_csv(path)
    assert [b.symbol for b in dataset.bars] == ["QQQ", "SPY"]
    assert dataset.bars[0].timestamp == dataset.bars[1].timestamp
    assert dataset.provenance["original_cutoff_verified"] is False
    assert dataset.provenance["source"] == "LOCAL_CSV_UNVERIFIED"


@pytest.mark.parametrize("row", [
    "SPY,2025-11-26T09:30:00,100,101,99,100,500",
    "SPY,2025-11-26T09:30:01Z,100,101,99,100,500",
    "SPY,2025-11-26T09:30:00Z,nan,101,99,100,500",
    "SPY,2025-11-26T09:30:00Z,100,99,98,100,500",
    "SPY,2025-11-26T09:30:00Z,100,101,99,100,-1",
])
def test_import_rejects_ambiguous_or_invalid_data(tmp_path, row):
    with pytest.raises(ValueError, match="CSV row"):
        data.load_csv(csv_file(tmp_path, [row]))


def test_duplicate_and_changed_sealed_csv_are_rejected(tmp_path):
    row = "SPY,2025-11-26T14:30:00Z,100,101,99,100,500"
    path = csv_file(tmp_path, [row, row])
    with pytest.raises(ValueError, match="duplicate"):
        data.load_csv(path)
    path = csv_file(tmp_path, [row])
    path.with_suffix(".csv.metadata.json").write_text(json.dumps({"csv_sha256": "wrong"}))
    with pytest.raises(ValueError, match="hash"):
        data.load_csv(path)


def test_floating_point_boundary_noise_is_not_a_material_ohlc_error(tmp_path):
    path = csv_file(tmp_path, ["SPY,2025-11-26T14:30:00Z,100,100,99,100.00000000000001,500"])
    assert len(data.load_csv(path).bars) == 1


def test_sip_download_paginates_seals_responses_and_never_saves_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "test-key-not-to-save")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test-secret-not-to-save")
    calls = []
    def page(url, key, secret):
        calls.append(parse_qs(urlparse(url).query))
        assert key == "test-key-not-to-save"
        assert secret == "test-secret-not-to-save"
        index = len(calls)
        return json.dumps({"bars": {"SPY": [{"t": f"2025-11-26T14:{29+index}:00Z",
                                              "o": 100, "h": 101, "l": 99, "c": 100, "v": 500}]},
                           "next_page_token": "second" if index == 1 else None}).encode()
    monkeypatch.setattr(data, "_get_page", page)
    path = tmp_path / "download.csv"
    result = data.download_alpaca(["SPY"], data.aware_time("2025-11-26T00:00:00Z"),
                                 data.aware_time("2025-11-27T00:00:00Z"), path)
    assert result["rows"] == 2
    assert calls[0]["feed"] == ["sip"] and calls[0]["adjustment"] == ["raw"]
    assert calls[1]["page_token"] == ["second"]
    assert len(result["response_sha256"]) == 2
    assert len(data.load_csv(path).bars) == 2
    for file in tmp_path.iterdir():
        assert "not-to-save" not in file.read_text()
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        data.download_alpaca(["SPY"], data.aware_time("2025-11-26T00:00:00Z"),
                             data.aware_time("2025-11-27T00:00:00Z"), path)
    assert path.read_bytes() == before


def test_recent_sip_missing_credentials_and_repeated_page_token_fail_before_success(tmp_path, monkeypatch):
    start, end = data.aware_time("2025-11-26T00:00:00Z"), data.aware_time("2025-11-27T00:00:00Z")
    with pytest.raises(ValueError, match="15 minutes"):
        data.download_alpaca(["SPY"], start, end, tmp_path / "x.csv", now=end)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="configure"):
        data.download_alpaca(["SPY"], start, end, tmp_path / "x.csv")
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setattr(data, "_get_page", lambda *args: b'{"bars": {}, "next_page_token": "again"}')
    with pytest.raises(RuntimeError, match="repeated"):
        data.download_alpaca(["SPY"], start, end, tmp_path / "x.csv")
    assert list(tmp_path.iterdir()) == []
