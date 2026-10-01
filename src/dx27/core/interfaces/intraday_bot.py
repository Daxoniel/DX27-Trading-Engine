from abc import ABC, abstractmethod

from dx27.core.models.bot_signal import BotSignal


class IntradayBot(ABC):

    @abstractmethod
    def evaluate(
        self,
        context,
        features,
    ) -> BotSignal | None:
        raise NotImplementedError