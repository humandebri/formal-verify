def midpoint (a b : Nat) : Nat := (a + b) / 2

theorem midpoint_le_max (a b : Nat) : midpoint a b ≤ max a b := by
  unfold midpoint
  omega

#print axioms midpoint_le_max
