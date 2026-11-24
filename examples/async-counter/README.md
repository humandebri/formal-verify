# Synthetic asynchronous completion example
The capacity invariant is count <= 1. A delayed completion after reset violates it. The Python implementation is independent of Quint; the event mapping is identity and the observable is the public event return value. This is an intentionally tiny, self-contained example.

Run `quint test counter.qnt` and `quint test fixed.qnt` to check the deterministic model regressions; run `quint verify counter.qnt --invariant=safe --max-steps=5` and the equivalent fixed check. Validated 2026-11-24 with Quint 0.34.0 (Apalache via JDK 21): `quint test` passes for both models; `quint run`/`quint verify --invariant=safe --max-steps=5` report a counterexample for counter.qnt (count reaches 2 via start, reset/restart, stale complete) and no violation for fixed.qnt. The replay sequence below matches that checker trace.

Run `python3 replay.py` (expected assertion failure) and `python3 replay.py --fixed` (expected success). Both use the same assertion. The synthetic fix saturates the count; in a real application review whether dropping a completion is allowed. No liveness claim is made.
