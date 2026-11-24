class Counter:
    def __init__(self, fixed=False):
        self.count = 0
        self.pending = False
        self.fixed = fixed
    def event(self, name):
        if name == 'start' and not self.pending and self.count == 0:
            self.pending = True
        elif name == 'reset':
            self.count = 1
        elif name == 'complete' and self.pending:
            self.count = min(1, self.count + 1) if self.fixed else self.count + 1
            self.pending = False
        return self.count
