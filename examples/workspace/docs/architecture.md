# Synthetic project architecture

Eagle is the payment processing service implemented in [src/EagleService.cs](../src/EagleService.cs).
The internal codename does not refer to a bird in this project.
The [ledger](../src/accounting/ledger.py) records settled transactions.
The [checkout client](../web/checkout.ts) initiates purchases.
The hypotheses in [ideas](ideas.md) have not been verified.
