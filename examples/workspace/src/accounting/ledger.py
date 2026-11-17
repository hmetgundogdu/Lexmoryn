"""Append settled transactions to the accounting journal."""


class Ledger:
    def append(self, transaction):
        return {"journal_entry": transaction, "state": "settled"}
