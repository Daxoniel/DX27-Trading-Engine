"""Deterministic daily activity anomaly detector (DX27 v0.1 design)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

from dx27.intelligence.sentinel.detection import DetectionResult
from dx27.intelligence.sentinel.events import (
    BaselineParameter,
    DetectedEvent,
    EventBaseline,
    EventDirection,
    EventEvidence,
    EventMagnitude,
    EventType,
    EvidenceLineage,
    RelevanceContext,
    SemanticFlag,
    UniverseContext,
)
from dx27.intelligence.sentinel.identity import (
    ContentIdentity,
    IdentityKind,
    make_content_identity,
    stable_content_hash,
)
from dx27.intelligence.sentinel.models import DataStatus, ObservationWindow
from dx27.intelligence.sentinel.observations import ObservationEnvelope


_DETECTOR_ID = "sentinel.activity_anomaly"
_DETECTOR_VERSION = "1"
_BASELINE_VERSION = "1"
_ROBUST_Z_SCALE = 0.6744897501960817


@dataclass(frozen=True)
class ActivityAnomalyConfig:
    """Explicit provisional policy and baseline definition for v0.1."""

    __canonical_type_id__ = "sentinel.activity_anomaly_config"
    __canonical_type_version__ = "1"

    lookback: int
    min_history: int
    relative_volume_threshold: float
    percentile_threshold: float
    robust_z_threshold: float | None
    economic_category: str
    detector_config_id: ContentIdentity = field(init=False)
    baseline_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.lookback, int) or isinstance(self.lookback, bool):
            raise TypeError("lookback must be an integer")
        if not isinstance(self.min_history, int) or isinstance(self.min_history, bool):
            raise TypeError("min_history must be an integer")
        if self.lookback < 2:
            raise ValueError("lookback must be at least 2")
        if self.min_history < 2:
            raise ValueError("min_history must be at least 2")
        if self.min_history > self.lookback:
            raise ValueError("min_history cannot exceed lookback")
        for field_name in ("relative_volume_threshold", "percentile_threshold"):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"{field_name} must be a float")
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f"{field_name} must be finite")
            object.__setattr__(self, field_name, value)
        if self.relative_volume_threshold <= 0:
            raise ValueError("relative_volume_threshold must be positive")
        if not 0 < self.percentile_threshold <= 1:
            raise ValueError("percentile_threshold must be in (0, 1]")
        if self.robust_z_threshold is not None:
            if not isinstance(self.robust_z_threshold, (int, float)) or isinstance(
                self.robust_z_threshold, bool
            ):
                raise TypeError("robust_z_threshold must be a float or None")
            threshold = float(self.robust_z_threshold)
            if not math.isfinite(threshold) or threshold <= 0:
                raise ValueError("robust_z_threshold must be finite and positive")
            object.__setattr__(self, "robust_z_threshold", threshold)
        if not isinstance(self.economic_category, str) or not self.economic_category.strip():
            raise ValueError("economic_category must be a non-empty string")

        baseline_semantics = {
            "baseline_version": _BASELINE_VERSION,
            "metric": "volume",
            "transform": "log1p",
            "center": "median",
            "dispersion": "MAD",
            "lookback": self.lookback,
            "min_history": self.min_history,
        }
        object.__setattr__(self, "baseline_id", stable_content_hash(baseline_semantics))
        object.__setattr__(
            self,
            "detector_config_id",
            make_content_identity(
                IdentityKind.CONFIGURATION,
                _DETECTOR_ID,
                _DETECTOR_VERSION,
                {
                    **baseline_semantics,
                    "relative_volume_threshold": self.relative_volume_threshold,
                    "percentile_threshold": self.percentile_threshold,
                    "robust_z_threshold": self.robust_z_threshold,
                    "economic_category": self.economic_category,
                },
            ),
        )


@dataclass(frozen=True)
class ActivityAnomalyMeasurement:
    """Diagnostic values calculated from one current and one baseline sample."""

    __canonical_type_id__ = "sentinel.activity_anomaly_measurement"
    __canonical_type_version__ = "1"

    current_volume: float
    sample_count: int
    median_volume: float
    median_log_volume: float
    mad_log_volume: float
    relative_volume: float | None
    historical_percentile: float
    robust_z: float | None


class ActivityAnomalyDetector:
    """Evaluate completed daily observations for elevated activity only."""

    def __init__(self, config: ActivityAnomalyConfig) -> None:
        if not isinstance(config, ActivityAnomalyConfig):
            raise TypeError("config must be an ActivityAnomalyConfig")
        self.config = config

    def measure(
        self,
        history: tuple[ObservationEnvelope, ...],
        current: ObservationEnvelope,
    ) -> ActivityAnomalyMeasurement:
        """Return the v0.1 diagnostic measurement or reject unusable input."""

        selected = self._selected_history(history, current)
        if len(selected) < self.config.min_history:
            raise ValueError("insufficient usable history for activity measurement")
        return self._measurement(selected, current)

    def detect(
        self,
        history: tuple[ObservationEnvelope, ...],
        current: ObservationEnvelope,
    ) -> DetectionResult:
        self._validate_current_scope(current)
        if current.data_status is not DataStatus.AVAILABLE:
            return DetectionResult(current.data_status)

        selected = self._selected_history(history, current)
        if len(selected) < self.config.min_history:
            return DetectionResult(DataStatus.INSUFFICIENT_HISTORY)
        measurement = self._measurement(selected, current)
        if not self._triggers(measurement):
            return DetectionResult(DataStatus.AVAILABLE)
        return DetectionResult(DataStatus.AVAILABLE, (self._event(selected, current, measurement),))

    def _validate_current_scope(self, current: ObservationEnvelope) -> None:
        if current.observation_window.timeframe != "1d":
            raise ValueError("activity anomaly detection requires a daily current observation")
        if current.observation_window.completed is not True:
            raise ValueError("current observation must be completed")

    def _selected_history(
        self,
        history: tuple[ObservationEnvelope, ...],
        current: ObservationEnvelope,
    ) -> tuple[ObservationEnvelope, ...]:
        self._validate_current_scope(current)
        seen_windows: set[tuple[object, object]] = set()
        usable: list[ObservationEnvelope] = []
        for item in history:
            if item.subject.subject_id != current.subject.subject_id:
                raise ValueError("history and current subject_id must match")
            window_key = (item.observation_window.start, item.observation_window.end)
            if window_key in seen_windows:
                raise ValueError("duplicate historical observation window")
            seen_windows.add(window_key)
            if (
                item.data_status is DataStatus.AVAILABLE
                and item.observation_window.end > current.observation_window.start
            ):
                raise ValueError("available history must precede the current observation period")
            if (
                item.data_status is DataStatus.AVAILABLE
                and item.observation_window.completed is True
                and item.observation_window.timeframe == "1d"
            ):
                if item.market_context is None:
                    raise ValueError("AVAILABLE history requires market_context")
                self._validated_volume(item.market_context.volume)
                usable.append(item)
        usable.sort(key=lambda item: (item.observation_window.end, item.observation_window.start))
        return tuple(usable[-self.config.lookback :])

    @staticmethod
    def _validated_volume(value: float) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError("volume must be numeric")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("volume must be finite")
        if value < 0:
            raise ValueError("volume cannot be negative")
        return value

    def _measurement(
        self,
        selected: tuple[ObservationEnvelope, ...],
        current: ObservationEnvelope,
    ) -> ActivityAnomalyMeasurement:
        if current.market_context is None:
            raise ValueError("AVAILABLE current observation requires market_context")
        current_volume = self._validated_volume(current.market_context.volume)
        volumes = tuple(self._validated_volume(item.market_context.volume) for item in selected)
        median_volume = float(median(volumes))
        log_volumes = tuple(math.log1p(value) for value in volumes)
        median_log_volume = float(median(log_volumes))
        mad_log_volume = float(
            median(abs(value - median_log_volume) for value in log_volumes)
        )
        relative_volume = current_volume / median_volume if median_volume > 0 else None
        historical_percentile = sum(value <= current_volume for value in volumes) / len(volumes)
        robust_z = None
        if mad_log_volume > 0:
            robust_z = (
                _ROBUST_Z_SCALE
                * (math.log1p(current_volume) - median_log_volume)
                / mad_log_volume
            )
        return ActivityAnomalyMeasurement(
            current_volume=current_volume,
            sample_count=len(volumes),
            median_volume=median_volume,
            median_log_volume=median_log_volume,
            mad_log_volume=mad_log_volume,
            relative_volume=relative_volume,
            historical_percentile=historical_percentile,
            robust_z=robust_z,
        )

    def _triggers(self, measurement: ActivityAnomalyMeasurement) -> bool:
        return (
            measurement.relative_volume is not None
            and measurement.relative_volume >= self.config.relative_volume_threshold
            and measurement.historical_percentile >= self.config.percentile_threshold
            and (
                self.config.robust_z_threshold is None
                or (
                    measurement.robust_z is not None
                    and measurement.robust_z >= self.config.robust_z_threshold
                )
            )
        )

    def _event(
        self,
        selected: tuple[ObservationEnvelope, ...],
        current: ObservationEnvelope,
        measurement: ActivityAnomalyMeasurement,
    ) -> DetectedEvent:
        baseline_window = ObservationWindow(
            start=selected[0].observation_window.start,
            end=selected[-1].observation_window.end,
            timeframe="1d",
        )
        source_ids = tuple(
            self._source_observation_id(item) for item in (*selected, current)
        )
        lineage = EvidenceLineage(
            evidence_family="ACTIVITY_VOLUME",
            source_observation_ids=source_ids,
            subject_ids=(current.subject.subject_id,),
            baseline_id=self.config.baseline_id,
        )
        evidence = [
            EventEvidence(
                metric="relative_volume",
                subject_id=current.subject.subject_id,
                value=measurement.relative_volume,
                unit="ratio",
                window=current.observation_window,
                data_status=DataStatus.AVAILABLE,
                lineage_id=lineage.lineage_id,
                reference_value=1.0,
            ),
            EventEvidence(
                metric="historical_volume_percentile",
                subject_id=current.subject.subject_id,
                value=measurement.historical_percentile,
                unit="ratio",
                window=current.observation_window,
                data_status=DataStatus.AVAILABLE,
                lineage_id=lineage.lineage_id,
            ),
        ]
        if measurement.robust_z is not None:
            evidence.append(
                EventEvidence(
                    metric="robust_volume_z",
                    subject_id=current.subject.subject_id,
                    value=measurement.robust_z,
                    unit="robust_z",
                    window=current.observation_window,
                    data_status=DataStatus.AVAILABLE,
                    lineage_id=lineage.lineage_id,
                )
            )
        membership = current.universe_membership
        return DetectedEvent(
            schema_version="1",
            detector_id=_DETECTOR_ID,
            detector_version=_DETECTOR_VERSION,
            detector_config_id=self.config.detector_config_id,
            event_type=EventType.ACTIVITY_ANOMALY,
            observed_at=current.observation_window.end,
            observation_window=current.observation_window,
            subjects=(current.subject,),
            economic_category=self.config.economic_category,
            direction=EventDirection.ELEVATED,
            magnitude=EventMagnitude(
                metric="relative_volume",
                value=measurement.relative_volume,
                unit="ratio",
                normalized_value=measurement.robust_z,
            ),
            baseline=EventBaseline(
                baseline_id=self.config.baseline_id,
                method="rolling_log1p_volume_median_mad",
                comparison_window=baseline_window,
                sample_count=measurement.sample_count,
                reference_value=measurement.median_volume,
                dispersion=measurement.mad_log_volume,
                parameters=(
                    BaselineParameter("lookback", self.config.lookback),
                    BaselineParameter("min_history", self.config.min_history),
                    BaselineParameter("transform", "log1p"),
                    BaselineParameter("center", "median"),
                    BaselineParameter("dispersion", "MAD"),
                ),
            ),
            evidence=tuple(evidence),
            evidence_lineage=(lineage,),
            provenance=current.provenance,
            universe_context=UniverseContext(
                tier=membership.tier.value,
                universe_config_id=membership.universe_config_id,
                membership_snapshot_id=membership.membership_snapshot_id,
            ),
            relevance_context=RelevanceContext(),
            semantic_flags=(SemanticFlag.ANOMALOUS,),
        )

    @staticmethod
    def _source_observation_id(item: ObservationEnvelope) -> str:
        """Identify lineage input from canonical facts owned by the observation."""

        return stable_content_hash(
            {
                "subject_id": item.subject.subject_id,
                "observation_window": item.observation_window,
                "provenance": item.provenance,
            }
        )
