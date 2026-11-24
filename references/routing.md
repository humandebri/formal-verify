# Routing
| Property | First choice | Escalation |
|---|---|---|
| Fixed-width arithmetic, equivalence, constraints | Z3 / cvc5 | Lean for independently checked theorem |
| Protocol, state machine, safety invariant | Quint | Inductive invariant or refinement proof |
| Existing Rust assertions, overflow, memory checks | Kani | Verus for deductive contracts |
| Rust functional correctness, loop invariants | Verus | Lean for isolated mathematical lemmas |
| Induction, unbounded mathematical statements | Lean | SMT for tractable subgoals |

Do not infer cross-tool consistency: explicitly map states, operations and assumptions. Two solvers agreeing on the same erroneous encoding do not validate the encoding. Cross-solver agreement is not independent kernel proof checking. Liveness needs explicit fairness and a supported temporal checking method; bounded safety is not liveness.
