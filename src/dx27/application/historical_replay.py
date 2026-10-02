"""Chronological, completed-bar historical replay primitives."""

from dataclasses import dataclass
from typing import Iterable, Iterator

from dx27.core.models.market_context import MarketContext
from dx27.core.models.trade_intent import TradeIntent


@dataclass(frozen=True)
class ReplayStep:
    """One completed replay bar and the history visible at that instant."""

    context: MarketContext
    history: tuple[MarketContext, ...]


class HistoricalReplay:
    """Expose immutable market-history prefixes in deterministic time order.

    A step is emitted only after its current bar is complete.  ``history``
    contains that completed bar and every earlier input bar, never a later bar.
    The replay intentionally does not know about bots, accounts, or execution.
    """

    def __init__(self, bars: Iterable[MarketContext]):
        ordered = tuple(sorted(bars, key=lambda bar: bar.timestamp))
        timestamps = [bar.timestamp for bar in ordered]
        if len(set(timestamps)) != len(timestamps):
            raise ValueError("replay bars must have unique timestamps")
        self._bars = ordered

    def __iter__(self) -> Iterator[ReplayStep]:
        visible: list[MarketContext] = []
        for bar in self._bars:
            visible.append(bar)
            yield ReplayStep(context=bar, history=tuple(visible))


class NextBarExecutionScheduler:
    """Schedule intents created after bar N for execution at bar N+1 open."""

    def __init__(self, execution):
        self._execution = execution
        self._pending: list[TradeIntent] = []

    def begin_step(self, step: ReplayStep):
        """Apply prior-bar intents before making the current bar decision."""
        self._execution.set_fill_context(
            step.context.timestamp,
            {step.context.symbol: step.context.open},
        )
        reports = tuple(self._execution.execute(intent) for intent in self._pending)
        self._pending = []
        return reports

    def queue(self, intents: Iterable[TradeIntent]) -> None:
        """Queue intents created after the completed current bar for the next open."""
        self._pending.extend(intents)

    def process_step(self, step: ReplayStep, new_intents: Iterable[TradeIntent] = ()):
        """Compatibility helper for callers that do not require post-fill state."""
        reports = self.begin_step(step)
        self.queue(new_intents)
        return reports
