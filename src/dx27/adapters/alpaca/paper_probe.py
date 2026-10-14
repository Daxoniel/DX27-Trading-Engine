"""Fail-closed, read-only connectivity probe for Alpaca *paper* accounts.

No broker execution method is implemented here. The destination host is fixed;
neither caller configuration nor environment variables can redirect to live.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PAPER_BASE = "https://paper-api.alpaca.markets"
_ALLOWED_PATHS = frozenset({"/v2/account", "/v2/clock"})
_SYMBOL_PATTERN = re.compile(r"[A-Z][A-Z0-9.]{0,9}\Z")


class PaperProbeError(Exception):
    """Error without potentially sensitive vendor response bodies."""


def parse_symbols(value: str) -> tuple[str, ...]:
    """Validate symbols before they become URL path components."""
    parts = [part.strip() for part in value.split(",")]
    if not parts or len(parts) > 10 or any(
        _SYMBOL_PATTERN.fullmatch(symbol) is None for symbol in parts
    ):
        raise PaperProbeError("Expected 1-10 comma-separated US stock/ETF symbols")
    if len(parts) != len(set(parts)):
        raise PaperProbeError("Duplicate symbols are not allowed")
    return tuple(parts)


class PaperReadOnlyClient:
    """Intentionally exposes GET only; never accepts arbitrary URLs."""

    def __init__(self, api_key: str, secret_key: str, *, timeout: float = 10.0):
        if not api_key or not secret_key:
            raise PaperProbeError(
                "Set APCA_API_KEY_ID and APCA_API_SECRET_KEY to PAPER credentials"
            )
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._api_key = api_key
        self._secret_key = secret_key
        self._timeout = timeout

    def get(self, path: str) -> dict[str, Any]:
        if path not in _ALLOWED_PATHS and not (
            path.startswith("/v2/assets/")
            and _SYMBOL_PATTERN.fullmatch(path.removeprefix("/v2/assets/"))
        ):
            raise PaperProbeError("Endpoint not in paper read-only allowlist")
        request = Request(
            PAPER_BASE + path,
            method="GET",
            headers={
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._secret_key,
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                body = response.read(262145)
        except HTTPError as exc:
            # Never echo error bodies, headers or credential-bearing objects.
            raise PaperProbeError(
                f"Paper GET {path} returned HTTP {exc.code}"
            ) from None
        except (URLError, OSError, TimeoutError):
            raise PaperProbeError(
                f"Paper GET {path} failed (network/timeout)"
            ) from None
        if len(body) > 262144:
            raise PaperProbeError(f"Paper GET {path} exceeded response size limit")
        try:
            document = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise PaperProbeError(f"Paper GET {path} returned invalid JSON") from None
        if not isinstance(document, dict):
            raise PaperProbeError(f"Paper GET {path} returned non-object JSON")
        return document


def run_probe(client: PaperReadOnlyClient, symbols: tuple[str, ...]) -> dict[str, Any]:
    """Return a deliberately minimized status record (no account identity)."""
    if not symbols or len(symbols) > 10 or any(
        _SYMBOL_PATTERN.fullmatch(symbol) is None for symbol in symbols
    ):
        raise PaperProbeError("Invalid symbols")
    account = client.get("/v2/account")
    clock = client.get("/v2/clock")
    status = account.get("status")
    is_open = clock.get("is_open")
    if not isinstance(status, str) or not isinstance(is_open, bool):
        raise PaperProbeError("Unexpected account or market-clock response")
    result = {
        "environment": "ALPACA_PAPER_ONLY",
        "connected": True,
        "execution_enabled": False,
        "account_status": status,
        "trading_blocked": account.get("trading_blocked") is True,
        "account_blocked": account.get("account_blocked") is True,
        "market_open": is_open,
        "next_open": clock.get("next_open"),
        "next_close": clock.get("next_close"),
        "assets": {},
        "market_data_feed_verified": False,
        "market_data_note": "Account probe does not test SIP/IEX data entitlement",
    }
    for symbol in symbols:
        asset = client.get(f"/v2/assets/{symbol}")
        if asset.get("symbol") != symbol:
            raise PaperProbeError(f"Unexpected asset symbol for {symbol}")
        result["assets"][symbol] = {
            "status": asset.get("status"),
            "tradable": asset.get("tradable") is True,
            "fractionable": asset.get("fractionable") is True,
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Alpaca Paper account + clock + asset probe; no orders"
    )
    parser.add_argument("--symbols", default="SPY,QQQ,IWM")
    args = parser.parse_args(argv)
    try:
        symbols = parse_symbols(args.symbols)
        client = PaperReadOnlyClient(
            os.environ.get("APCA_API_KEY_ID", ""),
            os.environ.get("APCA_API_SECRET_KEY", ""),
        )
        result = run_probe(client, symbols)
    except PaperProbeError as exc:
        print(f"ALPACA_PAPER_PROBE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
