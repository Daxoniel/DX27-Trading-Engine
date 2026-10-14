"""P0 read-only paper-account probe. This module has no order submission path."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


PAPER_BASE_URL = "https://paper-api.alpaca.markets"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get(path, key, secret):
    request = Request(PAPER_BASE_URL + path, method="GET",
                      headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
    with build_opener(_NoRedirect()).open(request, timeout=15) as response:
        return json.loads(response.read())


def _safe_observation(name, value):
    if name == "account":
        if (not isinstance(value, dict) or not isinstance(value.get("status"), str)
                or any(not isinstance(value.get(k), bool) for k in ("trading_blocked", "account_blocked"))):
            raise ValueError("invalid account response")
        # Keep the known status vocabulary; never copy arbitrary provider text.
        status = value["status"] if value["status"] in {
            "ACTIVE", "ONBOARDING", "SUBMISSION_FAILED", "SUBMITTED", "ACCOUNT_UPDATED",
            "APPROVAL_PENDING", "REJECTED", "DISABLED", "ACTION_REQUIRED"} else "UNKNOWN"
        return dict(account_status=status, trading_blocked=value["trading_blocked"],
                    account_blocked=value["account_blocked"])
    if name == "clock":
        if (not isinstance(value, dict) or not isinstance(value.get("is_open"), bool)
                or not isinstance(value.get("timestamp"), str)):
            raise ValueError("invalid clock response")
        timestamp = datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("clock must have an offset")
        return dict(market_is_open=value["is_open"], broker_timestamp=timestamp.isoformat())
    if not isinstance(value, list) or any(not isinstance(p, dict) or "symbol" not in p or "qty" not in p for p in value):
        raise ValueError("invalid positions response")
    return dict(position_count=len(value))


def probe_paper_account():
    key, secret = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    result = dict(task="P0", environment="paper", base_url=PAPER_BASE_URL,
                  checked_at=datetime.now(timezone.utc).isoformat(),
                  credentials_present=bool(key and secret), checks={},
                  automatic_orders_enabled=False, order_submission_tested=False,
                  realtime_data_verified=False)
    if not key or not secret:
        return dict(result, status="MISSING_CREDENTIALS")
    for name, path in (("account", "/v2/account"), ("clock", "/v2/clock"), ("positions", "/v2/positions")):
        try:
            result["checks"][name] = dict(status="PASS", **_safe_observation(name, _get(path, key, secret)))
        except HTTPError as exc:
            result["checks"][name] = dict(status="HTTP_ERROR", http_status=exc.code)
        except (URLError, TimeoutError, OSError):
            result["checks"][name] = dict(status="CONNECTION_ERROR")
        except (ValueError, TypeError, KeyError):
            result["checks"][name] = dict(status="INVALID_RESPONSE")
    result["status"] = "CONNECTED_READ_ONLY" if all(c["status"] == "PASS" for c in result["checks"].values()) else "NOT_VERIFIED"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="new JSON report; no credential/account identifiers saved")
    args = parser.parse_args(argv)
    path = Path(args.output)
    if path.exists():
        parser.error("output already exists; choose a new path")
    result = probe_paper_account()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(status=result["status"], output=str(path))))
    return 0 if result["status"] == "CONNECTED_READ_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
