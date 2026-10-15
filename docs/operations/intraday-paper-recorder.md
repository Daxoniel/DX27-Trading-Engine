# P2-H8 paper read-only HTTP recorder

The recorder makes authenticated **GET requests only** to the fixed
`https://paper-api.alpaca.markets` host. It has no submit/cancel methods, order
payloads, host override, automatic retry or connection to the execution gateway.
The strategy and historical execution model remain unchanged.

## Supported queries and controls

The allowlist contains account, clock, positions, bounded order lists,
client-order-ID lookup and bounded FILL/FEE/CFEE activity queries. Parameters
are validated before authentication, encoded as query parameters, and never
accepted as arbitrary paths or URLs. Booleans use API `true`/`false` strings.
Only GET is constructed. Activity windows and ID/page-token syntax are checked.

The default urllib opener retains configured proxies and certificate trust.
It rejects redirects, including 301/302/303/307/308, before issuing a redirected
authenticated request. The older account/clock/asset probe now shares this
redirect rejection while keeping its narrower endpoint allowlist.

Responses must return 200 from the requested URL, JSON content type, identity
encoding and the expected object/list top-level shape. Read size is at most
256 KiB plus one detection byte. Oversized or inconsistent Content-Length,
duplicate JSON keys, nonfinite numbers, invalid UTF-8, malformed/truncated JSON,
network/protocol errors and unexpected destinations fail with redacted codes.
No error body, credential, query ID or vendor exception message is printed.
Socket timeout defaults to 10 seconds (maximum 60); request count defaults to
20 (maximum 512). Failures consume the request budget and are not retried.

## Sampling and optional private recording

```sh
python -m dx27.adapters.alpaca.paper_recorder \
  --report work/paper-read-only-report.json
```

The default sample reads account, clock, positions, up to ten open orders and
one activity page of up to ten entries for the preceding day. It stops at the
first failed query. It does not paginate or claim a complete account snapshot.
`--after` and `--through` accept explicit UTC timestamps when another activity
window is needed. Credentials use the existing `APCA_API_KEY_ID` and
`APCA_API_SECRET_KEY` runtime bindings, without displaying their values.

Standard output and `--report` contain only minimized shape/count/status flags.
Account identity, cash, symbols, order IDs, descriptions and raw bodies are
omitted. `--recording work/private-paper-recording.json` explicitly writes
successful raw response bodies plus query/observation metadata. Raw recordings
may contain private account/order information; keep them in ignored local work
storage. Credential headers and failed response bodies are not recorded.
Files are created exclusively, with POSIX mode 0600; existing/aliased outputs
are rejected. No output is overwritten.

Exit codes: 0 means the five read-only samples succeeded; 2 means a request was
unavailable; 1 means setup, parameter or output failure. A successful sample is
**not** permission or evidence to trade. Every report/recording explicitly keeps
execution disabled, history incomplete and snapshot atomicity unverified.
The raw recording cannot automatically satisfy H7's complete/coherent producer
attestation or exact fill/fee evidence requirements.

## Actual read-only acceptance

The minimized [acceptance sample](../reports/intra-p2-h8/readonly-sample.json)
records actual successful queries against the configured paper endpoint. The
account is ACTIVE/USD. Positions, open orders and the sampled activity window
are empty. This verifies authenticated connectivity and top-level response
shapes only. No nonempty fill, fee attribution, terminal order lookup, complete
history, snapshot atomicity or order submission is established by empty results.
There were no submission/cancellation requests. Paid realtime feeds were not
queried or required.

Credential-free tests exercise fixed GET URLs, parameter encoding and limits,
all supported redirects through both default clients, body/JSON constraints,
protocol/network errors, request budgets, detached recording data, minimized
reporting and exclusive private exports. CI runs these on Ubuntu and Windows;
CI never invokes the authenticated sampler.

The next framework review should consolidate historical/recovery acceptance and
the remaining paper execution prerequisites. Actual fill/fee evidence, current
market-data readiness and controlled paper-order acceptance remain prerequisites
for enabling automated paper execution; the gateway stays closed meanwhile.
