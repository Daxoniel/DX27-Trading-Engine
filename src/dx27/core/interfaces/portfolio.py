from abc import ABC, abstractmethod

from dx27.core.models.portfolio_snapshot import PortfolioSnapshot


class PortfolioPort(ABC):

    @abstractmethod
    def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        raise NotImplementedError