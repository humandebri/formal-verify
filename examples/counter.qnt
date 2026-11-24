module counter {
  var n: int
  action init = n' = 0
  action step = n' = if (n < 3) n + 1 else 0
  val safe = n >= 0 and n <= 3
}
