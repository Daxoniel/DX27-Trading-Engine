"""Frozen R1 minute-prefix to historical-only intents. No broker transport.

The model backdates a 09:36 entry when that minute closes at 09:37.
These intents are engineering evidence, never executable current signals.
"""
from dataclasses import asdict
from datetime import timedelta, timezone
import hashlib

from dx27.adapters.intraday.lifecycle_journal import canonical
from dx27.research.opening_direction import OpeningDirectionFixture, RULE_VERSION
from paper_intents import require

CONTRACT = 'ORB_HISTORICAL_SIGNAL_BRIDGE:1'
MINUTE = timedelta(minutes=1)


def stamp(at):
    return at.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def historical_entry(session, bars, *, starting_cash, feed, source_sha256):
    """Exactly seven scheduled QQQ minutes; None explicitly means missing.

    Source seal/feed/calendar/capital are caller declarations, not authenticated.
    Identity seals seven bars plus archive provenance; later bars are not modeled.
    Changing the declared archive seal also changes identity. No session/PnL claim.
    """
    require(feed == 'sip', 'FROZEN_R1_REQUIRES_SIP_NO_FALLBACK')
    require(isinstance(source_sha256, str) and len(source_sha256) == 64
            and all(c in '0123456789abcdef' for c in source_sha256), 'SOURCE_SEAL_REQUIRED')
    require(isinstance(bars, (list, tuple)) and len(bars) == 7, 'EXACT_SEVEN_MINUTE_PREFIX_REQUIRED')
    model = OpeningDirectionFixture(session, 'R1', starting_cash=starting_cash)
    ticks = []
    for i, bar in enumerate(bars):
        at = session.opens_at + i * MINUTE
        model.on_closed_minute(at, bar, as_of=at + MINUTE)
        ticks.append(None if bar is None else {**asdict(bar), 'timestamp': stamp(bar.timestamp)})
    prefix = dict(contract=CONTRACT, rule_version=RULE_VERSION, profile='R1',
        session=session.session_id, opens_at=stamp(session.opens_at), closes_at=stamp(session.closes_at),
        starting_cash=model.initial_cash, feed=feed, source_sha256=source_sha256, ticks=ticks)
    digest = hashlib.sha256(canonical(prefix).encode()).hexdigest()
    entries = [f for f in model.fills if f.reason == 'ENTRY']
    require(len(entries) <= 1, 'MULTIPLE_ENTRY_MODEL_CONFLICT')
    # Missing prefix data invalidates the bridge even if a signal was frozen earlier.
    entry = entries[0] if entries and model.data_valid else None
    intent = None
    if entry:
        key = 'r1-entry-' + session.session_id + '-QQQ'
        intent = dict(intent_id=key, signal_key=key, session=session.session_id,
            symbol='QQQ', side=entry.side, quantity=entry.quantity,
            signal_at=stamp(model.signal_at), intent_ready_at=stamp(model.entry_at + MINUTE),
            origin='HISTORICAL_REPLAY', feed=feed, data_sha256=digest)
    return dict(contract=CONTRACT, mode='HISTORICAL_REPLAY', session=session.session_id,
        prefix_sha256=digest, source_sha256=source_sha256, intent=intent,
        decisions=model.decisions,
        outcome='ENTRY_REFERENCE' if intent else ('INVALID_PREFIX' if not model.data_valid else 'NO_ENTRY'),
        modeled_entry_at=stamp(entry.at) if entry else None,
        modeled_entry_reference=entry.reference if entry else None,
        earliest_closed_bar_availability=stamp(model.entry_at + MINUTE),
        availability='ASSUMED_AT_BAR_END_NOT_ORIGINAL_RECEIPT',
        complete_session_verified=False, source_authenticity_verified=False,
        actual_strategy_paper_pnl=None, current_order_eligible=False, execution_enabled=False)


def record_historical_entry(book, session, bars, **kwargs):
    """Idempotent durable entry intent; historical journals only, even for no-entry.

    A crash before registration can be retried. A crash after registration returns
    the same ID. Changed sealed inputs for a registered session halt its journal.
    No-entry decisions remain in the caller's report, not the intent journal.
    """
    require(book.mode == 'HISTORICAL_REPLAY', 'HISTORICAL_JOURNAL_REQUIRED')
    result = historical_entry(session, bars, **kwargs)
    key = 'r1-entry-' + session.session_id + '-QQQ'
    if result['intent'] is None and key in book.journal.state['signal_keys']:
        book._halt('REGISTERED_ENTRY_CHANGED_TO_NO_ENTRY')
    result['client_order_id'] = book.register(result['intent']) if result['intent'] else None
    return result
