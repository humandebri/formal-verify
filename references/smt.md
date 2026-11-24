# Z3 / cvc5

## Run
- `python3 scripts/verify.py run z3 model.smt2 --property <label> --out <dir>` (`z3 -smt2 model.smt2`).
- `python3 scripts/verify.py run cvc5 model.smt2 --property <label> --out <dir>` (`cvc5 --lang=smt2 --incremental --produce-models model.smt2`).
- `observed.smt_results` lists every `sat` / `unsat` / `unknown` in order; `(error ...)` lines make the outcome `input_error` (exit 3). Exit 0 says nothing about which answer you got: read `smt_results`.
- Solver timeouts: `(set-option :timeout 10000)` for Z3 (ms), `--tlimit-per=10000` for cvc5. A timeout or `unknown` is UNKNOWN, never PROVED.

## Query shape
Encode an entailment check as two queries in one file (see `examples/average.smt2`):
1. Declarations and assumptions, then `(check-sat)`: must be `sat`. `unsat` means the assumptions are contradictory and anything "follows" vacuously.
2. `(push 1)`, assert the **negation** of the property, `(check-sat)`, `(pop 1)`.
   - `sat`/`unsat` → the property holds for the encoding under the assumptions.
   - `sat`/`sat` → counterexample; add `(get-model)` (or `(get-value (x y))`) after the second check to extract it, then replay it on the source.
   - Anything with `unknown` → inconclusive.

## Encoding pitfalls
- Machine integers: use `(_ BitVec n)`, not `Int`. Pick the operator that matches the language: `bvslt`/`bvult`, `bvsdiv`/`bvudiv`, `bvsrem`/`bvsmod`/`bvurem`, `bvashr`/`bvlshr`.
- Overflow: SMT bitvector arithmetic wraps. If the source traps or has undefined behaviour on overflow (Rust debug, C signed), add explicit overflow conditions (e.g. widen with `zero_extend`/`sign_extend` and compare).
- Division by zero is total but unspecified-valued in SMT-LIB (`bvudiv x 0` is all ones). Guard it explicitly to match the source.
- `Int` and `Real` are unbounded: an `Int` proof does not transfer to fixed-width code.
- Set a logic (`(set-logic QF_BV)`) when you can; it is faster and rejects constructs outside the intended fragment.

## Cross-checking
Running both Z3 and cvc5 guards against a solver bug, not against an encoding mistake: two solvers agreeing on a wrong encoding prove the wrong thing. Review the encoding against source semantics; that review is the main trust step.

See https://microsoft.github.io/z3guide/docs/logic/basiccommands/ and https://cvc5.github.io/docs/ .
