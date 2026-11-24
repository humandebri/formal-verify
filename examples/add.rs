use vstd::prelude::*;
verus! {
    fn add(a: u64, b: u64) -> (r: u64)
        requires a as int + b as int <= u64::MAX as int,
        ensures r as int == a as int + b as int,
    { a + b }
}
fn main() {}
