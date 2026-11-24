# Verus

## Run
- `python3 scripts/verify.py run verus model.rs --property <label> --out <dir>` (`verus --output-json model.rs`). The collector runs inside `OUT/work`, so the compiled executable stays there.
- `observed.verus` copies `success`, `verified`, `errors` and `encountered-error` from the JSON. `errors > 0` → `violation_reported` (exit 1: an obligation failed, e.g. `possible arithmetic underflow/overflow` or a postcondition). `encountered-error` with `errors == 0` → `input_error` (exit 3: syntax, type or mode error before verification).
- Narrow the scope while iterating with `--verify-module <m>` or `--verify-function <f>`; report the full-crate result at the end (`is-verifying-entire-crate` in the JSON).
- Cargo projects: see `cargo verus --help` for the installed version.

## Before writing specs
1. Read the target function and all direct callers, callees, types and tests.
2. Decide whether it is Verus-supported. Async, FFI, trait-heavy dispatch, macro-heavy code, unresolved generics and I/O are extraction boundaries unless the code already verifies.
3. Extract or identify a small pure core without changing semantics, and verify the implementation file itself, not only a separate harness (unless a model-only proof was requested).
4. If the repository uses the `specgen` CLI (`Cargo.toml` plus `spec/`), follow the `specgen-cli` skill for target registration, scenario review, accepted specs, contract injection (`apply-contract`) and `specgen verify`.

## Writing specs
```rust
use vstd::prelude::*;
verus! {
fn max(a: u64, b: u64) -> (r: u64)
    ensures r >= a, r >= b, r == a || r == b,
{
    if a >= b { a } else { b }
}
fn double(n: u64) -> (r: u64)
    requires n <= 1000,
    ensures r == 2 * n,
{
    let mut i: u64 = 0;
    let mut r: u64 = 0;
    while i < n
        invariant i <= n, r == 2 * i, n <= 1000,
        decreases n - i,
    {
        i += 1;
        r += 2;
    }
    r
}
fn main() {}
}
```
- `requires` is the caller's obligation; check every call site meets it. `ensures` is the claim.
- Exec arithmetic is overflow-checked; spec arithmetic (`spec fn`, inside `ensures`) is on mathematical integers.
- Loops need `invariant` (restate everything still needed after the loop) and `decreases` for termination.
- Nonlinear facts (e.g. `s == i * (i + 1) / 2`) usually fail automatically; prove them with `by (nonlinear_arith)` or a separate `proof fn` lemma, and keep loop bounds strong enough to rule out exec overflow.

## Report
State which code is verified, which behaviour is only modeled, which runtime/library facts are assumed, and which parts are outside Verus support.

## Trust review
Search the verified code for `assume(`, `admit(`, `#[verifier::external_body]`, `#[verifier::external]`, `external_fn_specification`, `#[verifier::truncate]` and trusted `spec` axioms (`#[verifier::external_body] proof fn` or `broadcast` axioms). Each is unverified trust; list it in the report. Code outside `verus! {}` is not verified at all.

See https://verus-lang.github.io/verus/guide/ .
