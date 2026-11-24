#[kani::proof]
fn check() {
    let a: u32 = kani::any();
    let b: u32 = kani::any();
    let actual = (a & b) + ((a ^ b) >> 1);
    assert_eq!(actual as u64, (a as u64 + b as u64) / 2);
}
