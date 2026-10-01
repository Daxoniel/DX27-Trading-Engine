from abc import ABC, abstractmethod

from dx27.core.models.account_snapshot import AccountSnapshot


class AccountPort(ABC):

    @abstractmethod
    def get_account_snapshot(self) -> AccountSnapshot:
        raise NotImplementedError