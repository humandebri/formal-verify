# Lean 4

## Run
- Single file: `python3 scripts/verify.py run lean Model.lean --property <theorem> --out <dir>` (`lean -DwarningAsError=true Model.lean`).
- Lake project (Mathlib etc.): run with `--cwd <project root>`; inside the project use `lake env lean -DwarningAsError=true Model.lean` or `lake build`. Building an untrusted project runs its code: sandbox it.
- Put `#print axioms <theorem>` after every claimed theorem. The collector parses it into `observed.lean_axioms` and:
  - `untrusted_axioms` (exit 1) if anything beyond `propext`, `Classical.choice`, `Quot.sound` is used (`sorryAx`, user `axiom`s, `native_decide` auxiliaries);
  - a warning if the `--property` theorem has no `#print axioms` output (axioms unchecked).
- Errors: `declaration uses 'sorry'` and failed tactics → `violation_reported` (exit 1); parse/name errors (`unexpected token`, `unknown identifier`) → `input_error` (exit 3). This split is pattern-based; read the log.

## Writing proofs
```lean
theorem avg_le (a b : Nat) (h : a ≤ b) : (a + b) / 2 ≤ b := by
  omega
#print axioms avg_le
```
- `omega` (linear Nat/Int arithmetic), `simp`, `decide` (small decidable goals) and `induction` are kernel-checked.
- `native_decide` trusts the compiler: in Lean 4.36 it adds an auxiliary axiom such as `thm._native.native_decide.ax_1_1` (older versions show `Lean.ofReduceBool`). The collector flags it; accept only if the report states that extra trust. `bv_decide` (needs `import Std.Tactic.BVDecide`) checked against 4.36 uses only standard axioms.
- Fixed-width integers: use `UInt32`/`BitVec 32` to model machine arithmetic; `Nat` theorems do not transfer.

## Modeling rules
- Name the theorem in plain language first, then define state and operations with minimal data types; prefer finite, structural models before real-world fidelity.
- Turn external facts into explicit `axiom`s or theorem parameters (parameters are preferable: they do not trip the axiom check and stay visible at use sites).
- Do not prove a stronger theorem than claimed, and do not encode implementation detail the theorem does not need.
- Impossibility results must rest on an explicit exhaustiveness lemma; if exhaustiveness is informal, label the theorem conditional.
- Track every `sorry` with the exact missing lemma or modeling decision. See `proof-planning.md` for the overall structure.

## Review checklist
- Does the theorem statement say what is claimed? Check hypotheses for contradictions (a false hypothesis proves anything) and that definitions match the source.
- `sorry`, `admit`, user `axiom`s, `@[implemented_by]`, `@[extern]`, and `unsafe` definitions used in the statement are trust boundaries.
- Warnings-as-errors catches `sorry` but not axioms: `#print axioms` is required.

See https://lean-lang.org/ and https://lean-lang.org/theorem_proving_in_lean4/ .
