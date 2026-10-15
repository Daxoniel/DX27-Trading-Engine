"""Fixed-host GET-only paper HTTP sampling. Never produces complete evidence."""

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from http.client import HTTPException
from math import isfinite
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from dx27.adapters.alpaca.paper_contract import PAPER_ENDPOINT, timestamp_revision
from dx27.domains.intraday.order_lifecycle import identifier


class PaperRecorderError(ValueError):
    """Stable error codes without credentials, query IDs or vendor messages."""


class RejectPaperRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _require(condition, code):
    if not condition:
        raise PaperRecorderError(code)


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _bounded_int(value, low, high):
    return type(value) is int and low <= value <= high


def _query(path, params):
    _require(isinstance(path, str) and isinstance(params, dict), "INVALID_PAPER_QUERY")
    if path in {"/v2/account", "/v2/clock", "/v2/positions"}:
        _require(not params, "INVALID_PAPER_QUERY")
    elif path == "/v2/orders":
        _require(set(params) == {"status", "limit", "direction", "nested"}, "INVALID_PAPER_QUERY")
        _require(params["status"] in ("open", "closed", "all")
                 and _bounded_int(params["limit"], 1, 500) and params["direction"] in ("asc", "desc")
                 and type(params["nested"]) is bool, "INVALID_PAPER_QUERY")
    elif path == "/v2/orders:by_client_order_id":
        _require(set(params) == {"client_order_id"}, "INVALID_PAPER_QUERY")
        identifier(params["client_order_id"])
    elif path == "/v2/account/activities":
        required = {"activity_types", "after", "until", "direction", "page_size"}
        _require(required <= set(params) <= required | {"page_token"}, "INVALID_PAPER_QUERY")
        _require(params["activity_types"] == "FILL,FEE,CFEE" and params["direction"] == "asc"
                 and _bounded_int(params["page_size"], 1, 100), "INVALID_PAPER_QUERY")
        _require(timestamp_revision(params["after"]) < timestamp_revision(params["until"]), "INVALID_PAPER_QUERY")
        if "page_token" in params:
            identifier(params["page_token"])
    else:
        raise PaperRecorderError("PAPER_GET_PATH_REJECTED")
    return urlencode({k: str(v).lower() if type(v) is bool else v for k, v in sorted(params.items())})


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _float(value):
    result = float(value)
    if not isfinite(result):
        raise ValueError
    return result


def _constant(value):
    raise ValueError


class PaperHttpRecorder:
    def __init__(self, api_key, secret_key, *, timeout=10.0, max_requests=20):
        _require(all(isinstance(v, str) and 0 < len(v) <= 4096 and not re.search(r"[\r\n]", v)
                     for v in (api_key, secret_key)), "PAPER_CREDENTIALS_REQUIRED")
        _require(type(timeout) in (int, float) and isfinite(timeout) and 0 < timeout <= 60,
                 "INVALID_PAPER_TIMEOUT")
        _require(_bounded_int(max_requests, 1, 512), "INVALID_PAPER_REQUEST_LIMIT")
        self._headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key,
                         "Accept": "application/json", "Accept-Encoding": "identity"}
        self._opener = build_opener(RejectPaperRedirects())
        self.timeout, self.max_requests, self.attempts, self.entries = timeout, max_requests, 0, []

    def get(self, path, params=None):
        try:
            params = {} if params is None else params
            query = _query(path, params)
            _require(self.attempts < self.max_requests, "PAPER_REQUEST_LIMIT")
            self.attempts += 1
            url = PAPER_ENDPOINT + path + ("?" + query if query else "")
            request = Request(url, method="GET", headers=self._headers)
            started = _utc()
            with self._opener.open(request, timeout=self.timeout) as response:
                _require(response.status == 200 and response.geturl() == url, "UNEXPECTED_PAPER_RESPONSE")
                _require(response.headers.get_content_type() == "application/json", "PAPER_RESPONSE_NOT_JSON")
                _require(response.headers.get("Content-Encoding", "identity").lower() == "identity",
                         "UNSUPPORTED_PAPER_ENCODING")
                length = response.headers.get("Content-Length")
                _require(length is None or (length.isascii() and length.isdigit() and int(length) <= 262144),
                         "PAPER_RESPONSE_TOO_LARGE")
                raw = response.read(262145)
                _require(len(raw) <= 262144, "PAPER_RESPONSE_TOO_LARGE")
                _require(length is None or int(length) == len(raw), "TRUNCATED_PAPER_RESPONSE")
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                              parse_float=_float, parse_constant=_constant)
            expected = list if path in {"/v2/positions", "/v2/orders", "/v2/account/activities"} else dict
            _require(isinstance(body, expected), "INVALID_PAPER_RESPONSE_SHAPE")
            self.entries.append(dict(path=path, params=dict(params), status=200, started_at=started,
                                     observed_at=_utc(), body=body))
            return deepcopy(body)
        except PaperRecorderError:
            raise
        except HTTPError as exc:
            code = exc.code
            exc.close()
            raise PaperRecorderError(f"PAPER_HTTP_STATUS_{code}") from None
        except (URLError, OSError, TimeoutError, HTTPException):
            raise PaperRecorderError("PAPER_NETWORK_UNAVAILABLE") from None
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            raise PaperRecorderError("INVALID_PAPER_RESPONSE_OR_QUERY") from None

    def recording(self):
        # A sampled page is never an attestation of full history or coherent state.
        return dict(contract="P2-H8", endpoint=PAPER_ENDPOINT, history_complete=False,
                    coherent=False, execution_enabled=False, entries=deepcopy(self.entries))


def sample_read_only(recorder, *, after, through):
    # Validate all requested ranges before sending the first authenticated GET.
    activity = dict(activity_types="FILL,FEE,CFEE", after=after, until=through, direction="asc", page_size=10)
    _query("/v2/account/activities", activity)
    queries = [("account", "/v2/account", {}), ("clock", "/v2/clock", {}),
               ("positions", "/v2/positions", {}),
               ("orders", "/v2/orders", dict(status="open", limit=10, direction="asc", nested=False)),
               ("activities", "/v2/account/activities", activity)]
    results = {}
    for label, path, params in queries:
        try:
            body = recorder.get(path, params)
            entry = dict(status="OBSERVED", shape="list" if isinstance(body, list) else "object")
            if isinstance(body, list):
                entry["sample_count"] = len(body)
            if label == "account":
                entry["active_usd"] = body.get("status") == "ACTIVE" and body.get("currency") == "USD"
            if label == "activities":
                entry["fill_samples"] = sum(row.get("activity_type") == "FILL" for row in body if isinstance(row, dict))
                entry["fee_samples"] = sum(row.get("activity_type") in ("FEE", "CFEE") for row in body if isinstance(row, dict))
                entry["fee_order_attribution_verified"] = False
            results[label] = entry
        except PaperRecorderError as exc:
            results[label] = dict(status="UNAVAILABLE", code=str(exc))
            break  # No automatic retries or further queries after a failed request.
    return dict(contract="P2-H8", mode="PAPER_GET_ONLY_SAMPLE", endpoints=results,
                sampling_complete=len(results) == len(queries) and all(r["status"] == "OBSERVED" for r in results.values()),
                evidence_complete=False, history_complete=False, snapshot_atomicity_verified=False,
                execution_enabled=False, real_orders_sent=False)


def _write_new(path, value):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only paper HTTP sample; no orders or full evidence claim")
    parser.add_argument("--after")
    parser.add_argument("--through")
    parser.add_argument("--report", type=Path, help="New minimized status file")
    parser.add_argument("--recording", type=Path, help="New private raw-body recording, may contain account/order identities")
    args = parser.parse_args(argv)
    try:
        paths = [p.resolve() for p in (args.report, args.recording) if p is not None]
        _require(len(set(paths)) == len(paths) and not any(p.exists() for p in paths), "OUTPUT_ALREADY_EXISTS_OR_ALIASED")
        through = args.through or _utc()
        after = args.after or (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        _query("/v2/account/activities", dict(activity_types="FILL,FEE,CFEE", after=after, until=through,
                                            direction="asc", page_size=10))
        recorder = PaperHttpRecorder(os.environ.get("APCA_API_KEY_ID", ""), os.environ.get("APCA_API_SECRET_KEY", ""))
        report = sample_read_only(recorder, after=after, through=through)
        if args.recording:
            _write_new(args.recording, recorder.recording())
        if args.report:
            _write_new(args.report, report)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["sampling_complete"] else 2
    except (PaperRecorderError, OSError, ValueError):
        print(json.dumps(dict(code="PAPER_RECORDER_FAILED", execution_enabled=False, real_orders_sent=False)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
