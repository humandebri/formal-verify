# Kani

## Run
- Standalone file: `python3 scripts/verify.py run kani model.rs --property <harness> --out <dir>` (`kani model.rs --harness <harness>`).
- Cargo project: run `cargo kani --harness <harness>` from the crate root (or the collector with `--cwd <crate root>` once Cargo support is needed; the collector currently invokes standalone `kani`).
- Outcomes: `VERIFICATION:- FAILED` → `violation_reported` (exit 1); compile errors or an unknown harness name → `input_error` (exit 3). `observed.signals` keeps the harness summary line.

## Harness design
```rust
#[cfg(kani)]
#[kani::proof]
#[kani::unwind(9)]
fn check() {
    let a: u32 = kani::any();
    let b: u32 = kani::any();
    kani::assume(b != 0);            // precondition: state it, never assume the property
    let r = my_div(a, b);
    assert!(r <= a);
    kani::cover!(a > 0 && r == 0);   // non-vacuity: this branch must be reachable
}
```
- `kani::any()` gives every value of the type; constrain with `kani::assume` only for real preconditions. An over-strong assume makes the proof vacuous; add `kani::cover!` for important branches and check they report SATISFIED.
- Arithmetic overflow, out-of-bounds indexing, unwrap on None, and panics are checked automatically.

## Bounds and completeness
- Loops are unrolled. Set `#[kani::unwind(n)]` (or `--default-unwind n`). Kani adds unwinding assertions: if they pass, the result is complete for the harness's input space. If the run needs `--no-unwinding-checks` to finish, report BOUNDED_SAFE with the bound, not PROVED.
- A successful harness proves the asserted properties for every input the harness admits, nothing about inputs it excludes or code it does not call.

## Review checklist
- Assumptions (`kani::assume`), stubs (`#[kani::stub]`), and `--harness` selection: is the harness you ran the one you claim?
- Unsupported features are reported as such; a check that is "UNREACHABLE" or a feature that is unsupported is not a pass.
- Counterexamples: rerun with `--concrete-playback=print` to get a unit test that reproduces the failing input on the real code.

See https://model-checking.github.io/kani/ .
