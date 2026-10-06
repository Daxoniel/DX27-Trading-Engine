"""Deterministic daily volume anomaly detection for Sentinel."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

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
    """Explicit provisional trigger and rolling-baseline configuration."""

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
        self._validate_positive_finite(
            self.relative_volume_threshold, "relative_volume_threshold"
        )
        if (
            isinstance(self.percentile_threshold, bool)
            or not isinstance(self.percentile_threshold, (int, float))
            or not math.isfinite(self.percentile_threshold)
            or not 0 < self.percentile_threshold <= 1
        ):
            raise ValueError("percentile_threshold must be finite and in (0, 1]")
        if self.robust_z_threshold is not None:
            self._validate_positive_finite(self.robust_z_threshold, "robust_z_threshold")
        if not isinstance(self.economic_category, str) or not self.economic_category.strip():
            raise ValueError("economic_category must be a non-empty string")

        baseline_semantics = {
            "version": _BASELINE_VERSION,
            "metric": "volume",
            "transform": "log1p",
            "center": "median",
            "dispersion": "MAD",
            "lookback": self.lookback,
            "min_history": self.min_history,
        }
        object.__setattr__(
            self,
            "baseline_id",
            f"sentinel.activity_volume_baseline:{stable_content_hash(baseline_semantics)}",
        )
        object.__setattr__(
            self,
            "detector_config_id",
            make_content_identity(
                IdentityKind.CONFIGURATION,
                _DETECTOR_ID,
                _DETECTOR_VERSION,
                {
                    "detector_version": _DETECTOR_VERSION,
                    "lookback": self.lookback,
                    "min_history": self.min_history,
                    "relative_volume_threshold": self.relative_volume_threshold,
                    "percentile_threshold": self.percentile_threshold,
                    "robust_z_threshold": self.robust_z_threshold,
                    "economic_category": self.economic_category,
                },
            ),
        )

    @staticmethod
    def _validate_positive_finite(value: object, name: str) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True)
class ActivityAnomalyMeasurement:
    """Diagnostic values produced by the daily activity baseline."""

    current_volume: float
    sample_count: int
    median_volume: float
    median_log_volume: float
    mad_log_volume: float
    relative_volume: float | None
    historical_percentile: float
    robust_z: float | None


class ActivityAnomalyDetector:
    """Evaluate one completed daily observation against prior daily volume."""

    def __init__(self, config: ActivityAnomalyConfig) -> None:
        if not isinstance(config, ActivityAnomalyConfig):
            raise TypeError("config must be an ActivityAnomalyConfig")
        self.config = config

    def measure(
        self,
        history: tuple[ObservationEnvelope, ...],
        current: ObservationEnvelope,
    ) -> ActivityAnomalyMeasurement:
        selected = self._selected_history(history, current)
        if len(selected) < self.config.min_history:
            raise ValueError("insufficient usable history")
        return self._measure_selected(selected, current)

    def detect(
        self,
        history: tuple[ObservationEnvelope, ...],
        current: ObservationEnvelope,
    ) -> DetectionResult:
        self._validate_current(current)
        self._validate_history(history, current)
        if current.data_status is not DataStatus.AVAILABLE:
            return DetectionResult(current.data_status)

        selected = self._usable_history(history)[-self.config.lookback :]
        if len(selected) < self.config.min_history:
            return DetectionResult(DataStatus.INSUFFICIENT_HISTORY)
        measurement = self._measure_selected(selected, current)
        if not self._triggered(measurement):
            return DetectionResult(DataStatus.AVAILABLE)
        return DetectionResult(DataStatus.AVAILABLE, (self._event(selected, current, measurement),))

    def _selected_history(
        self,
        history: tuple[ObservationEnvelope, ...],
        current: ObservationEnvelope,
    ) -> tuple[ObservationEnvelope, ...]:
        self._validate_current(current)
        self._validate_history(history, current)
        if current.data_status is not DataStatus.AVAILABLE:
            raise ValueError("current observation is not AVAILABLE")
        return self._usable_history(history)[-self.config.lookback :]

    @staticmethod
    def _validate_current(current: ObservationEnvelope) -> None:
        if not isinstance(current, ObservationEnvelope):
            raise TypeError("current must be an ObservationEnvelope")
        window = current.observation_window
        if window.timeframe != "1d" or window.completed is not True:
            raise ValueError("current observation must be a completed daily observation")

    @staticmethod
    def _validate_history(
        history: tuple[ObservationEnvelope, ...], current: ObservationEnvelope
    ) -> None:
        if not isinstance(history, tuple):
            raise TypeError("history must be a tuple")
        seen_windows: set[tuple[object, object]] = set()
        for item in history:
            if not isinstance(item, ObservationEnvelope):
                raise TypeError("history must contain only ObservationEnvelope values")
            if item.subject.subject_id != current.subject.subject_id:
                raise ValueError("history and current subject_id must match")
            key = (item.observation_window.start, item.observation_window.end)
            if key in seen_windows:
                raise ValueError("duplicate history observation window")
            seen_windows.add(key)
            if (
                item.data_status is DataStatus.AVAILABLE
                and item.observation_window.end > current.observation_window.start
            ):
                raise ValueError("AVAILABLE history cannot overlap or follow the current period")

    @staticmethod
    def _usable_history(
        history: tuple[ObservationEnvelope, ...],
    ) -> tuple[ObservationEnvelope, ...]:
        usable = (
            item
            for item in history
            if item.data_status is DataStatus.AVAILABLE
            and item.observation_window.timeframe == "1d"
            and item.observation_window.completed is True
            and item.market_context is not None
        )
        return tuple(
            sorted(
                usable,
                key=lambda item: (item.observation_window.end, item.observation_window.start),
            )
        )

    def _measure_selected(
        self,
        selected: tuple[ObservationEnvelope, ...],
        current: ObservationEnvelope,
    ) -> ActivityAnomalyMeasurement:
        volumes = tuple(self._volume(item) for item in selected)
        current_volume = self._volume(current)
        median_volume = float(statistics.median(volumes))
        log_volumes = tuple(math.log1p(value) for value in volumes)
        median_log_volume = float(statistics.median(log_volumes))
        mad_log_volume = float(
            statistics.median(abs(value - median_log_volume) for value in log_volumes)
        )
        robust_z = None
        if mad_log_volume > 0:
            robust_z = (
                _ROBUST_Z_SCALE
                * (math.log1p(current_volume) - median_log_volume)
                / mad_log_volume
            )
        relative_volume = current_volume / median_volume if median_volume > 0 else None
        percentile = sum(value <= current_volume for value in volumes) / len(volumes)
        return ActivityAnomalyMeasurement(
            current_volume=current_volume,
            sample_count=len(volumes),
            median_volume=median_volume,
            median_log_volume=median_log_volume,
            mad_log_volume=mad_log_volume,
            relative_volume=relative_volume,
            historical_percentile=percentile,
            robust_z=robust_z,
        )

    @staticmethod
    def _volume(item: ObservationEnvelope) -> float:
        context = item.market_context
        if context is None:
            raise ValueError("volume requires market_context")
        value = context.volume
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("volume must be numeric, finite, and non-negative")
        return float(value)

    def _triggered(self, measurement: ActivityAnomalyMeasurement) -> bool:
        relative = measurement.relative_volume
        robust_threshold = self.config.robust_z_threshold
        return (
            relative is not None
            and relative >= self.config.relative_volume_threshold
            and measurement.historical_percentile >= self.config.percentile_threshold
            and (
                robust_threshold is None
                or (
                    measurement.robust_z is not None
                    and measurement.robust_z >= robust_threshold
                )
            )
        )

    def _event(
        self,
        selected: tuple[ObservationEnvelope, ...],
        current: ObservationEnvelope,
        measurement: ActivityAnomalyMeasurement,
    ) -> DetectedEvent:
        relative_volume = measurement.relative_volume
        if relative_volume is None:  # Protected by the trigger predicate.
            raise ValueError("triggered event requires relative volume")
        source_ids = tuple(self._source_observation_id(item) for item in (*selected, current))
        lineage = EvidenceLineage(
            evidence_family="ACTIVITY_VOLUME",
            source_observation_ids=source_ids,
            subject_ids=(current.subject.subject_id,),
            baseline_id=self.config.baseline_id,
        )
        evidence = [
            EventEvidence(
                "relative_volume",
                current.subject.subject_id,
                relative_volume,
                "ratio",
                current.observation_window,
                DataStatus.AVAILABLE,
                lineage.lineage_id,
                reference_value=1.0,
            ),
            EventEvidence(
                "historical_volume_percentile",
                current.subject.subject_id,
                measurement.historical_percentile,
                "ratio",
                current.observation_window,
                DataStatus.AVAILABLE,
                lineage.lineage_id,
            ),
        ]
        if measurement.robust_z is not None:
            evidence.append(
                EventEvidence(
                    "robust_volume_z",
                    current.subject.subject_id,
                    measurement.robust_z,
                    "robust_z",
                    current.observation_window,
                    DataStatus.AVAILABLE,
                    lineage.lineage_id,
                )
            )
        comparison_window = ObservationWindow(
            selected[0].observation_window.start,
            selected[-1].observation_window.end,
            "1d",
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
                "relative_volume",
                relative_volume,
                "ratio",
                normalized_value=measurement.robust_z,
            ),
            baseline=EventBaseline(
                baseline_id=self.config.baseline_id,
                method="rolling_log1p_volume_median_mad",
                comparison_window=comparison_window,
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
                membership.tier.value,
                membership.universe_config_id,
                membership.membership_snapshot_id,
            ),
            relevance_context=RelevanceContext(),
            semantic_flags=(SemanticFlag.ANOMALOUS,),
        )

    @staticmethod
    def _source_observation_id(item: ObservationEnvelope) -> str:
        return stable_content_hash(
            {
                "subject_id": item.subject.subject_id,
                "observation_window": item.observation_window,
                "provenance": item.provenance,
            }
        )
