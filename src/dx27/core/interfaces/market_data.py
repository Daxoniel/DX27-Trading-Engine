from abc import ABC, abstractmethod


class MarketDataPort(ABC):

    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        period: str,
        interval: str,
    ):
        raise NotImplementedError