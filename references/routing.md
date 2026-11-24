# Routing
| Property | First choice | Escalation |
|---|---|---|
| Fixed-width arithmetic, equivalence, constraints | Z3 / cvc5 | Lean for independently checked theorem |
| Protocol, state machine, safety invariant | Quint | Inductive invariant or refinement proof |
| Existing Rust assertions, overflow, memory checks | Kani | Verus for deductive contracts |
| Rust functional correctness, loop invariants | Verus | Lean for isolated mathematical lemmas |
| Induction, unbounded mathematical statements | Lean | SMT for tractable subgoals |
| Abstract theorem, impossibility result, protocol/storage model, paper-style argument | Lean (see `proof-planning.md`) | Verus for the Rust implementation obligations |
| API whose illegal states or call sequences should be unrepresentable | Idris2 (`idris2.md`) | Port the evidence types to the production language |
| Vague claim, runtime-dependent property, or no clear model yet | Proof plan (`proof-planning.md`), not proof code | Pick a backend once the plan is agreed |

Verus is a poor first choice when the target is mostly async, FFI, trait-heavy dispatch, macro-heavy, unresolved generics or I/O: extract a small pure core first, or use Kani/Quint. For mixed systems sequence the tools (prove the abstract model in Lean, then the Rust obligations in Verus) instead of mixing proofs early.

Pause and ask when the property would change public API, storage layout or security assumptions, depends on undocumented runtime behaviour, needs unsupported Verus features whose extraction would change semantics, or is stronger than the model can justify.

Do not infer cross-tool consistency: explicitly map states, operations and assumptions. Two solvers agreeing on the same erroneous encoding do not validate the encoding. Cross-solver agreement is not independent kernel proof checking. Liveness needs explicit fairness and a supported temporal checking method; bounded safety is not liveness.
