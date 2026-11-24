# Application modeling and counterexample-driven development

Inspired by mizchi's case study: https://zenn.dev/mizchi/articles/quint-application-modeling (2026-08-19). The workflow below is independently developed; examples are synthetic.

## Before modeling
- Pin source revision, property ID and observable assertion. Map every relevant state and action to source symbols, event boundaries and observable effects. Record exclusions and assumptions in a case manifest.
- Prefer a small model per property. Separate durable state, cached state, in-flight operations and external effects. Treat time, delivery and scheduling as explicit inputs. Do not merge asynchronous initiation/completion into an atomic step unless justified by the actual implementation.
- Examine retries, duplicate or stale responses, cancellation, crashes/restarts, concurrent updates, clock boundaries and partial failure when relevant. Do not introduce impossible behavior without marking it as an overapproximation.
- Reduce domains only with a documented mapping back to concrete inputs; preserve boundary comparisons, units and arithmetic semantics. Never assume scaling preserves all behavior.

## Search and evidence
1. Typecheck; demonstrate reachable initial states and meaningful actions. Simulate with recorded seed, sample count and depth. Then check using Apalache (bounded) and optionally TLC (finite exhaustive only if completed). Record engine, version, actual bounds and whether the search completed. Check deadlocks separately; a safety invariant is not a liveness proof.
2. Preserve raw trace; minimize events while retaining the violation. Freeze a deterministic Quint `run` that expects the violation on the buggy model. Save the original model and a separate fixed model with the same invariant.
3. Map each abstract action to concrete public API calls and inputs. Use injected clocks/events rather than sleeps, mock only external dependencies, and assert externally observable safety. Preserve before-fix failure and after-fix success from the SAME test. A failing setup or compilation is not RED.
4. If replay cannot reproduce, mark MODEL_ONLY or MODEL_MISMATCH (confirmed discrepancy), investigate missing guards or incorrect abstraction. Do not report an implementation bug. Distinguish model safety from implementation reproduction independently.
5. Fix only when authorized. Re-run deterministic model tests and exploration; retain original negative model. Check adjacent failure modes. Record operational assumptions and safety versus availability/latency costs; define monitoring or enforcement for assumptions. For liveness, specify fairness and progress conditions separately.
6. Escalate arithmetic obligations to SMT, Rust implementation paths to Kani, supported Rust contracts to Verus, and general theorems to Lean only when needed. A proof of a local obligation does not establish refinement between models and implementation.

## Completion
A confirmed implementation bug requires concrete replay on the original revision; a confirmed fix additionally requires unchanged regression passing on the fixed revision and review of the updated model. A model-only result remains useful but must be labeled. Use the manifest checker to collect evidence hashes. Review raw logs and actual assertions manually. Never treat its success as proof.
