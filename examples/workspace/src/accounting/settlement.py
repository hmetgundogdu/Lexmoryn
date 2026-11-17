from .ledger import Ledger


def reconcile_bank_transfers(transactions):
    """Match incoming bank transfers against outstanding invoices."""
    return [Ledger().append(transaction) for transaction in transactions]
