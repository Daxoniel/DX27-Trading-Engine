from abc import ABC, abstractmethod

from dx27.core.models.account_snapshot import AccountSnapshot
from dx27.core.models.bot_signal import BotSignal
from dx27.core.models.portfolio_snapshot import PortfolioSnapshot
from dx27.core.models.portfolio_target import PortfolioTarget


class PortfolioConstructor(ABC):

    @abstractmethod
    def construct(
        self,
        signals: tuple[BotSignal, ...],
        account: AccountSnapshot,
        portfolio: PortfolioSnapshot,
    ) -> tuple[PortfolioTarget, ...]:
        """
        Convert strategy signals into target portfolio positions.

        Responsibilities may include:
        - strategy capital budgets
        - signal weighting
        - conflict resolution
        - existing-position awareness
        - target sizing

        This layer does not execute orders.
        """
        raise NotImplementedError