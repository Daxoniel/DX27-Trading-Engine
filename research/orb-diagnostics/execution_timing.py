"""Offline quote matching contract. No networking, orders, or evidence authentication."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import re


def clock(value):
    if not isinstance(value, str) or re.search(r'\.\d{7,}', value):
        raise ValueError('TIMESTAMP_REQUIRES_EXPLICIT_MICROSECOND_OR_COARSER_PRECISION')
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError('AWARE_CLOCK_REQUIRED')
    return t.astimezone(timezone.utc)


def positive_integer(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError('POSITIVE_INTEGER_REQUIRED')
    return value


def positive_price(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('INVALID_QUOTE_PRICE')
    price = Decimal(str(value))
    if not price.is_finite() or price <= 0:
        raise ValueError('INVALID_QUOTE_PRICE')
    return price


def micros(delta):
    return (delta.days*86400+delta.seconds)*1000000+delta.microseconds


def evaluate_timing(trace, quotes, *, max_quote_age_us):
    """First eligible quote in RECEIPT order, using only its inspected prefix.

    All times are assertions in input. Structural validity never authenticates a
    source, synchronizes clocks, calibrates latency, or authorizes submission.
    Quote size is modeled top-of-book shares, not guaranteed available liquidity.
    """
    flags = dict(execution_enabled=False, authenticity_verified=False,
                 actual_fill_verified=False, live_latency_verified=False,
                 costs_calibrated=False, runtime_guard=False)
    if max_quote_age_us is None:
        return dict(status='BLOCKED_MISSING_QUOTE_FRESHNESS_POLICY', **flags)
    positive_integer(max_quote_age_us)
    if trace.get('contract') != 'ORB_OFFLINE_TIMING:1':
        raise ValueError('TIMING_CONTRACT_REQUIRED')
    kind = trace.get('observation_kind')
    if kind not in ('SYNTHETIC', 'RECORDED_OBSERVATION', 'HISTORICAL_RECONSTRUCTION'):
        raise ValueError('OBSERVATION_KIND_REQUIRED')
    if trace.get('side') not in ('BUY', 'SELL'):
        raise ValueError('INVALID_MODEL_SIDE')
    quantity = positive_integer(trace['quantity'])
    if trace.get('required_feed') not in ('sip', 'iex') or not isinstance(trace.get('symbol'), str):
        raise ValueError('EXPLICIT_FEED_AND_SYMBOL_REQUIRED')
    names = ('signal_window_end', 'last_input_available_at', 'last_input_received_at',
             'decision_at', 'intent_ready_at')
    times = [clock(trace[n]) for n in names]
    if any(a > b for a,b in zip(times,times[1:])):
        raise ValueError('SIGNAL_OR_DECISION_PRECEDES_INPUT')
    end, available, received, decision, intent = times
    previous_receipt, previous_sequence, ids = None, None, set()
    skipped = Counter()
    for inspected, q in enumerate(quotes, 1):
        qid = q['quote_id']
        if not isinstance(qid, str) or not qid or qid in ids:
            raise ValueError('INVALID_OR_DUPLICATE_QUOTE_ID')
        ids.add(qid)
        seq = positive_integer(q['receipt_sequence'])
        event, receipt = clock(q['event_at']), clock(q['received_at'])
        if event > receipt:
            raise ValueError('QUOTE_EVENT_AFTER_RECEIPT_CLOCK_UNRESOLVED')
        if (previous_receipt is not None and receipt < previous_receipt) or (
                previous_sequence is not None and seq <= previous_sequence):
            raise ValueError('NONMONOTONIC_RECEIPT_STREAM')
        previous_receipt, previous_sequence = receipt, seq
        bid, ask = positive_price(q['bid']), positive_price(q['ask'])
        if ask < bid:
            raise ValueError('CROSSED_QUOTE')
        if q.get('size_unit') != 'SHARES':
            raise ValueError('EXPLICIT_SHARE_SIZE_REQUIRED')
        bid_size, ask_size = positive_integer(q['bid_size']), positive_integer(q['ask_size'])
        if q.get('symbol') != trace['symbol'] or q.get('feed') != trace['required_feed']:
            skipped['SYMBOL_OR_FEED_MISMATCH'] += 1
            continue
        if receipt < intent or event < intent:
            skipped['BEFORE_INTENT_READY'] += 1
            continue
        age = micros(receipt-event)
        if age > max_quote_age_us:
            skipped['STALE_QUOTE'] += 1
            continue
        size = ask_size if trace['side'] == 'BUY' else bid_size
        if quantity > size:
            skipped['INSUFFICIENT_DISPLAYED_SIZE'] += 1
            continue
        return dict(status=('SYNTHETIC_MODEL_MATCH' if kind == 'SYNTHETIC'
                             else 'UNAUTHENTICATED_MODEL_MATCH'), **flags,
            observation_kind=kind, quote_id=qid, inspected_quotes=inspected,
            skipped_before_match=dict(sorted(skipped.items())),
            model_match_at=receipt.isoformat(), modeled_reference_price=str(ask if trace['side']=='BUY' else bid),
            reference_kind='ASK' if trace['side']=='BUY' else 'BID', quantity=quantity,
            feed=trace['required_feed'], quote_age_us=age,
            declared_intervals_us=dict(input_available_after_window=micros(available-end),
                delivery_after_availability=micros(received-available),decision_after_receive=micros(decision-received),
                intent_after_decision=micros(intent-decision),quote_wait_after_intent=micros(receipt-intent)))
    return dict(status='NO_ELIGIBLE_QUOTE', **flags, observation_kind=kind,
                inspected_quotes=len(quotes), skipped=dict(sorted(skipped.items())))
