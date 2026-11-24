# Proof planning and structure

Use this before writing proof code when the claim is vague, spans runtime assumptions, needs a model extracted first, or when the requested deliverable is a plan. When the claim and scope are already clear and small, go straight to the backend.

## Structure every formalization
- **Axioms**: external runtime, library, hardware, protocol or language facts. Ground each in a primary source or local code; anything unsourced stays an explicit axiom (or a theorem parameter), never a silent assumption.
- **Definitions**: the mathematical model: state, operations, observations (keep observations separate from transitions).
- **Lemmas**: local facts the theorem needs; prove these first.
- **Theorems**: the user-facing claims, no stronger than requested.
- **Refinement links**: why the model corresponds to the real code or system. Without one, label the result model-only.

Prove the smallest core claim first, then add implementation correspondence. Report the result in four buckets: proven, modeled, assumed, unverified.

## Plan template
```markdown
# <claim or target>

## Tool choice
- Chosen tool: <Lean 4 | Verus | Kani | Quint | SMT | Idris2 | mixed>
- Reason: <one sentence>

## Claim
- Informal claim:
- Formal target:
- Out of scope:

## Model
- State / operations / observations:
- External axioms (with sources):

## Proof structure
- Definitions:
- Lemmas:
- Theorems:
- Refinement obligations:

## Implementation link
- Source files or modules:
- Verified core:
- Assumed runtime/library behaviour:
- Unsupported or excluded code:

## Validation
- Check command (`scripts/verify.py run ...`):
- Existing tests / new scenarios:
- Acceptance criteria:

## Known gaps
- Unproved claims, `sorry`s, trusted axioms, model-code mismatch:
```
Keep each field brief; drop sections only when the work is clearly model-only or implementation-only.

## Worked mapping (storage trilemma)
- State: logical pages, physical locations, capacity, dirty pages.
- Operations: append-only commit, in-place commit, shadow commit.
- Properties: atomicity, bounded allocation, write locality.
- Theorem: the three are incompatible under the stated design-space assumptions, which needs an explicit exhaustiveness lemma over commit strategies; if exhaustiveness is argued informally, the theorem is conditional.
