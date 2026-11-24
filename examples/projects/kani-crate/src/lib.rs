/// Midpoint without overflow.
pub fn midpoint(a: u32, b: u32) -> u32 {
    (a & b) + ((a ^ b) >> 1)
}

#[cfg(kani)]
mod proofs {
    use super::*;

    #[kani::proof]
    fn midpoint_matches_wide() {
        let a: u32 = kani::any();
        let b: u32 = kani::any();
        let wide = ((a as u64 + b as u64) / 2) as u32;
        assert_eq!(midpoint(a, b), wide);
    }
}
