# Idris2 (type-level API design)

Use Idris2 when the deliverable is an API whose type signatures make invalid states or call sequences unrepresentable. `scripts/verify.py` has no Idris2 backend: run `idris2 --check Model.idr` directly and keep the log. Ask before installing it.

## Good targets
- State machines with allowed transitions only.
- Capabilities or evidence tokens, e.g. `SingleMessage`, `NoAwait`, `NoInterCanisterCall`, ownership tokens.
- Resource protocols where linear (use-once) usage matters.
- Length, bounds, phase or permission constraints that should be compile-time facts.

## Steps
1. Name the invalid operation that should become unrepresentable.
2. Represent phases, permissions or resources as types.
3. Make each operation a function that requires the right evidence.
4. Keep proofs next to constructors and transition functions.
5. Decide how the Idris2 model maps back to production code. Without a mapping, report it as a design prototype.

## Limits
- Idris2 does not verify existing Rust or C code; a type-safe Idris2 API is not a proof that a separate implementation obeys it.
- Runtime and platform semantics still need axioms or separate tests.

When recommending Idris2, give: the illegal states ruled out, the evidence types, the transition functions, and the refinement obligation back to production code.
