from abc import ABC, abstractmethod

from dx27.core.models.bot_signal import BotSignal


class Strategy(ABC):

    @abstractmethod
    def evaluate(self, context) -> BotSignal | None:
        """Evaluate current market context and optionally emit a signal."""
        raise NotImplementedError