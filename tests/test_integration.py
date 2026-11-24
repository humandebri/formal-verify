"""Real-verifier checks of the bundled examples. Slow; opt in with FORMAL_VERIFY_INTEGRATION=1."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
P = ROOT / 'scripts/verify.py'
EX = ROOT / 'examples'
ENABLED = os.environ.get('FORMAL_VERIFY_INTEGRATION') == '1'
REQUIRE_ALL = os.environ.get('FORMAL_VERIFY_REQUIRE_ALL') == '1'  # CI: a missing tool fails instead of skipping

CASES = [
    # (name, argv, expected exit, expected outcome)
    ('z3_average', ['z3', EX / 'average.smt2', '--property', 'average_equivalence'], 0, 'clean'),
    ('cvc5_average', ['cvc5', EX / 'average.smt2', '--property', 'average_equivalence'], 0, 'clean'),
    ('quint_counter', ['quint', EX / 'counter.qnt', '--property', 'safe', '--bound', '10'], 0, 'clean'),
    ('quint_async_bug', ['quint', EX / 'async-counter/counter.qnt', '--property', 'safe', '--bound', '5'], 1, 'violation_reported'),
    ('quint_async_fixed', ['quint', EX / 'async-counter/fixed.qnt', '--property', 'safe', '--bound', '5'], 0, 'clean'),
    ('quint_async_test', ['quint', EX / 'async-counter/fixed.qnt', '--quint-mode', 'test'], 0, 'clean'),
    ('quint_typo', ['quint', EX / 'async-counter/counter.qnt', '--property', 'saef', '--bound', '5'], 3, 'input_error'),
    ('verus_add', ['verus', EX / 'add.rs', '--property', 'add'], 0, 'clean'),
    ('kani_average', ['kani', EX / 'kani_average.rs', '--property', 'check'], 0, 'clean'),
    ('kani_wrong_harness', ['kani', EX / 'kani_average.rs', '--property', 'nope'], 3, 'input_error'),
    ('lean_add', ['lean', EX / 'Add.lean', '--property', 'add_comm_example'], 0, 'clean'),
]


def usable(tool):
    path = shutil.which(tool)
    if not path:
        return False
    try:
        return subprocess.run([path, '--version'], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(ENABLED, 'set FORMAL_VERIFY_INTEGRATION=1 to run real verifiers')
class Integration(unittest.TestCase):
    def test_examples(self):
        for name, argv, code, outcome in CASES:
            with self.subTest(name), tempfile.TemporaryDirectory() as t:
                if not usable(argv[0]):
                    if REQUIRE_ALL:
                        self.fail(f'{argv[0]} not usable')
                    self.skipTest(f'{argv[0]} not usable')
                out = pathlib.Path(t) / 'evidence'
                r = subprocess.run([sys.executable, str(P), 'run', *map(str, argv), '--timeout', '300', '--out', str(out)],
                                   capture_output=True, text=True, cwd=t)
                data = json.loads((out / 'result.json').read_text())
                self.assertEqual((r.returncode, data['observed']['outcome']), (code, outcome), data['observed'])


if __name__ == '__main__':
    unittest.main()
