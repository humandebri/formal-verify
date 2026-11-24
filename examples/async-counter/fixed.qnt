module fixed {
  var count: int
  var pending: bool
  action init = all { count' = 0, pending' = false }
  action start = all { not(pending), count == 0, count' = count, pending' = true }
  action reset = all { count' = 1, pending' = pending }
  action complete = all { pending, count' = if (count == 0) 1 else count, pending' = false }
  action step = any { start, reset, complete }
  val safe = count <= 1
  run staleCompletionTest = init.then(start).then(reset).then(complete).expect(safe)
}
