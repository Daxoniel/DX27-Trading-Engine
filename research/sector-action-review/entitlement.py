"""Isolated cash-plus-CVR entitlement ledger; no broker or strategy integration.

Only verified raw-share quantities are accepted. Adjusted-price proxy units
cannot establish actual ownership. A payable date never proves receipt.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


def amount(value):
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError('FINITE_NONNEGATIVE_DECIMAL_REQUIRED')
    return value


@dataclass
class Ledger:
    cash: Decimal
    shares: dict
    receivables: dict = field(default_factory=dict)
    rights: dict = field(default_factory=dict)
    applied: set = field(default_factory=set)

    def __post_init__(self):
        amount(self.cash)
        self.shares = dict(self.shares)
        for quantity in self.shares.values():
            amount(quantity)

    def convert(self, event_id, symbol, right_id, effective_date, cash_per_share,
                *, raw_shares_verified=False, legal_terms_verified=False):
        """Cancel owned stock, recognize gross receivable and unpriced rights."""
        if not raw_shares_verified or not legal_terms_verified:
            raise ValueError('VERIFIED_RAW_OWNERSHIP_AND_LEGAL_TERMS_REQUIRED')
        date.fromisoformat(effective_date)
        amount(cash_per_share)
        if not event_id or not symbol or not right_id or event_id in self.applied:
            raise ValueError('INVALID_OR_DUPLICATE_EVENT')
        quantity = self.shares.get(symbol, Decimal(0))
        if amount(quantity) <= 0:
            raise ValueError('OWNED_SHARES_REQUIRED')
        # No conversion fee, tax or fair-value assumption is introduced here.
        self.receivables[event_id] = dict(amount=quantity * cash_per_share,
                                         effective_date=effective_date)
        self.rights[right_id] = self.rights.get(right_id, Decimal(0)) + quantity
        del self.shares[symbol]
        self.applied.add(event_id)

    def receive(self, event_id, received_date, gross_amount, *, receipt_verified=False):
        """Full gross settlement only; withholding/partial payments need a new model."""
        if not receipt_verified:
            raise ValueError('OBSERVED_RECEIPT_REQUIRED')
        date.fromisoformat(received_date)
        amount(gross_amount)
        receivable = self.receivables[event_id]
        if received_date < receivable['effective_date'] or gross_amount != receivable['amount']:
            raise ValueError('RECEIPT_DATE_OR_AMOUNT_MISMATCH')
        self.cash += gross_amount
        del self.receivables[event_id]

    def equity(self):
        # Unknown CVR fair value prevents a certified total NAV, even after payment.
        if self.shares or self.rights:
            raise ValueError('UNPRICED_ASSETS_PREVENT_TOTAL_NAV')
        return self.cash + sum((r['amount'] for r in self.receivables.values()), Decimal(0))
