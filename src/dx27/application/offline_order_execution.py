"""Offline-only coordinator. Durable claim precedes every simulated call."""

from dx27.adapters.intraday.order_book import OfflineOrderBook
from dx27.adapters.intraday.scripted_broker import ScriptedBroker
from dx27.domains.intraday.order_lifecycle import OrderRequest


class OfflineOrderExecution:
    def __init__(self, book: OfflineOrderBook, broker: ScriptedBroker):
        if not isinstance(broker, ScriptedBroker):
            raise TypeError("P2-H coordinator accepts only the local scripted broker")
        if book.namespace != broker.namespace or book.initial_cash != broker.initial_cash:
            raise ValueError("offline coordinator namespace/initial account mismatch")
        self.book, self.broker = book, broker

    def reconcile(self):
        try:
            return self.book.reconcile(self.broker.snapshot())
        except (TimeoutError, OSError):
            return self.book.pause_reconciliation("snapshot_unavailable")

    def submit(self, client_order_id):
        if not self.book.claim_submission(client_order_id):
            return self.book.order(client_order_id)
        request = OrderRequest(**self.book.order(client_order_id)["request"])
        try:
            report = self.broker.submit(client_order_id, request)
        except (TimeoutError, OSError):
            self.book.uncertain(client_order_id)
            return self.book.order(client_order_id)
        except Exception:
            self.book.uncertain(client_order_id)
            raise
        self.book.apply(report)
        return self.book.order(client_order_id)

    def cancel(self, client_order_id):
        if not self.book.claim_cancel(client_order_id):
            return self.book.order(client_order_id)
        try:
            report = self.broker.cancel(client_order_id)
        except (TimeoutError, OSError):
            self.book.uncertain(client_order_id, cancel=True)
            return self.book.order(client_order_id)
        except Exception:
            self.book.uncertain(client_order_id, cancel=True)
            raise
        self.book.apply(report)
        return self.book.order(client_order_id)
