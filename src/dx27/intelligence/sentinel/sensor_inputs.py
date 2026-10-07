"""Normalization bridge for scalar series and existing OHLCV observations.

Providers and their schemas do not enter Sentinel. The application supplies
validated bindings and separately evidenced capture/publication metadata.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from zoneinfo import ZoneInfo

from dx27.intelligence.sentinel.models import DataStatus, ObservationWindow
from dx27.intelligence.sentinel.observations import ObservationEnvelope
from dx27.intelligence.sentinel.sensor_contracts import FeedBinding, SeriesPoint, VintageMode
from dx27.intelligence.sentinel.session_calendar import SessionCalendar, utc


@dataclass(frozen=True)
class AvailabilityStamp:
    published_at: datetime | None
    first_seen_at: datetime
    source_record_id: str
    revision_id: str
    payload_sha256: str
    vintage_mode: VintageMode = VintageMode.RECORDED_AS_AVAILABLE


def normalize_series_point(binding: FeedBinding, window: ObservationWindow,
                           status: DataStatus, raw_value: float | None,
                           stamp: AvailabilityStamp) -> SeriesPoint:
    value = None
    if status is DataStatus.AVAILABLE:
        try:
            value = binding.normalize(raw_value)
            if not math.isfinite(value):
                raise ValueError('nonfinite normalized value')
        except (ValueError, TypeError, OverflowError):
            status = DataStatus.SOURCE_ERROR
            value = None
    elif raw_value is not None:
        raise ValueError('non-AVAILABLE raw series value must be null')
    return SeriesPoint(binding.subject_ref, window, status, value, binding.normalized_unit,
                       stamp.published_at, stamp.first_seen_at, binding.source_id,
                       stamp.source_record_id, binding.source_version, stamp.revision_id,
                       stamp.payload_sha256, stamp.vintage_mode)


def normalize_ohlcv_close(envelope: ObservationEnvelope, binding: FeedBinding,
                          stamp: AvailabilityStamp, calendar: SessionCalendar,
                          session_id: str) -> SeriesPoint:
    if envelope.subject != binding.subject_ref:
        raise ValueError('OHLCV subject does not match binding')
    if (binding.price_basis != 'TOTAL_RETURN_AS_AVAILABLE' or binding.normalized_unit != 'USD'
            or binding.observation_label_policy != 'XNYS_SESSION' or binding.source_calendar_id != 'XNYS'):
        raise ValueError('ETF requires explicitly validated causal total-return price basis')
    if not any(p.source_id == binding.source_id and p.source_record_id == stamp.source_record_id
               and p.source_version == binding.source_version for p in envelope.provenance):
        raise ValueError('availability metadata must match OHLCV provenance')
    session = calendar.get(session_id)
    window = envelope.observation_window
    if window.start != session.opens_at or window.end != session.closes_at or window.timeframe != '1d':
        raise ValueError('OHLCV window must match the actual completed daily session')
    status = envelope.data_status
    value = None
    if status is DataStatus.AVAILABLE:
        ctx = envelope.market_context
        numbers = (ctx.open, ctx.high, ctx.low, ctx.close, ctx.volume)
        try:
            timestamp = utc(ctx.timestamp)
            policy = binding.ohlcv_timestamp_policy
            if policy == 'SESSION_END':
                time_matches = timestamp == session.closes_at
            elif policy == 'SESSION_OPEN':
                time_matches = timestamp == session.opens_at
            else:
                zone = timezone.utc if policy == 'UTC_DATE_LABEL' else ZoneInfo('America/New_York')
                label = timestamp.astimezone(zone)
                time_matches = label.date().isoformat() == session_id and (label.hour,label.minute,label.second,label.microsecond) == (0,0,0,0)
        except (TypeError, ValueError):
            time_matches = False
        if (not time_matches or ctx.timeframe != '1d' or (binding.subject_ref.symbol is not None and ctx.symbol != binding.subject_ref.symbol)
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in numbers)
                or min(ctx.open, ctx.high, ctx.low, ctx.close) <= 0 or ctx.volume < 0
                or ctx.high < max(ctx.open, ctx.close, ctx.low) or ctx.low > min(ctx.open, ctx.close, ctx.high)):
            status = DataStatus.SOURCE_ERROR
        else:
            value = ctx.close
    return normalize_series_point(binding, window, status, value, stamp)
