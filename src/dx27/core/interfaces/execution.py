from abc import ABC, abstractmethod

from dx27.core.models.execution_report import ExecutionReport
from dx27.core.models.trade_intent import TradeIntent


class ExecutionPort(ABC):

    @abstractmethod
    def execute(
        self,
        intent: TradeIntent,
    ) -> ExecutionReport:
        raise NotImplementedError