"""Offline review of recorded paper evidence against the offline order book."""

from dx27.adapters.alpaca.paper_contract import (
    PAPER_ENDPOINT, PaperContractError, normalize_trade_update, recorded_snapshot, timestamp_revision,
)


def reconcile_recording(book, bundle):
    # Normalize the entire bundle before applying any individual report.
    try:
        snapshot = recorded_snapshot(bundle)
    except PaperContractError:
        return book.pause_reconciliation("invalid_paper_recording")
    return book.reconcile(snapshot)


def apply_recorded_update(book, update, *, cumulative_fee, cumulative_notional):
    try:
        report = normalize_trade_update(update, cumulative_fee=cumulative_fee,
                                        cumulative_notional=cumulative_notional)
    except PaperContractError:
        book.pause_reconciliation("invalid_paper_update")
        return "PAUSED"
    return book.apply(report)


def review_admission(book, *, endpoint, account, clock, asset, symbol, captured_at, now):
    """Data/account preflight only, never an order/risk approval or execution gate.

    Caller supplies an explicit replay clock. A five-second freshness bound makes
    stale/future evidence fail closed. Current sizing/reservation checks remain
    the responsibility of the existing order book and strategy risk policy.
    """
    issues = []
    if endpoint != PAPER_ENDPOINT:
        issues.append("paper_endpoint_required")
    if not book.ready:
        issues.append("reconciliation_required")
    if not isinstance(account, dict) or (account.get("status") != "ACTIVE" or account.get("currency") != "USD" or any(
        account.get(k) is not False for k in ("trading_blocked", "account_blocked", "trade_suspended_by_user")
    )):
        issues.append("account_not_ready")
    if not isinstance(clock, dict) or clock.get("is_open") is not True:
        issues.append("market_not_open")
    if not isinstance(asset, dict) or (asset.get("symbol") != symbol or asset.get("class") != "us_equity"
            or asset.get("status") != "active" or asset.get("tradable") is not True):
        issues.append("asset_not_ready")
    try:
        current, captured, clock_at = map(timestamp_revision, (now, captured_at, clock["timestamp"]))
        if not (0 <= current - captured <= 5_000_000_000 and 0 <= current - clock_at <= 5_000_000_000):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        issues.append("stale_or_invalid_evidence")
    return dict(review_ready=not issues, issues=issues, execution_enabled=False,
                scope="RECORDED_PAPER_PREFLIGHT_ONLY")
