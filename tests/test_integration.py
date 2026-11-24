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
    ('kani_project', ['kani', '--project', EX / 'projects/kani-crate', '--property', 'midpoint_matches_wide'], 0, 'clean'),
    ('verus_project', ['verus', '--project', EX / 'projects/verus-crate', '--property', 'max'], 0, 'clean'),
    ('lean_project', ['lean', 'LeanLake/Midpoint.lean', '--project', EX / 'projects/lean-lake', '--property', 'midpoint_le_max'], 0, 'clean'),
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
                r = subprocess.run([sys.executable, str(P), 'run', *map(str, argv), '--timeout', '900', '--out', str(out)],
                                   capture_output=True, text=True, cwd=t)
                data = json.loads((out / 'result.json').read_text())
                logs = {n: (out / n).read_text(errors='replace')[-3000:] for n in ('stdout.log', 'stderr.log')}
                self.assertEqual((r.returncode, data['observed']['outcome']), (code, outcome),
                                 json.dumps({'observed': data['observed'], 'command': data['command'], **logs}, indent=1))

    def test_async_counter_case_end_to_end(self):
        """Real Quint results for the bundled example pass case_check's cross-checks."""
        if not usable('quint'):
            if REQUIRE_ALL:
                self.fail('quint not usable')
            self.skipTest('quint not usable')
        ex = EX / 'async-counter'
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            for name in ('counter.qnt', 'fixed.qnt', 'app.py', 'replay.py'):
                shutil.copy(ex / name, root / name)
            for name, model in (('model_run', 'counter.qnt'), ('fixed_run', 'fixed.qnt')):
                subprocess.run([sys.executable, str(P), 'run', 'quint', model, '--property', 'safe', '--bound', '5',
                                '--quint-itf', '--out', str(root / name)], cwd=root, capture_output=True, timeout=900)
            red = subprocess.run([sys.executable, 'replay.py'], cwd=root, capture_output=True, text=True)
            green = subprocess.run([sys.executable, 'replay.py', '--fixed'], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(red.returncode, 0)
            self.assertEqual(green.returncode, 0)
            (root / 'red.log').write_text(red.stdout + red.stderr)
            (root / 'green.log').write_text(green.stdout + green.stderr)
            (root / 'fixed_run' / 'model_test.log').write_text('see fixed_run/stdout.log')
            manifest = {
                'property_id': 'safe', 'property': 'count <= 1', 'source_revision': 'example',
                'assumptions': [], 'exclusions': [], 'tradeoffs': [],
                'mapping': [{'abstract_action': 'complete', 'source_symbol': 'app.complete',
                             'concrete_inputs': 'stale token', 'observable_effect': 'count'}],
                'claim': 'FIX_REPLAYED',
                'evidence': {
                    'model': 'counter.qnt', 'fixed_model': 'fixed.qnt',
                    'trace': 'model_run/trace.itf.json', 'model_regression': 'counter.qnt',
                    'implementation_test': 'replay.py', 'red_log': 'red.log', 'green_log': 'green.log',
                    'fixed_check_log': 'fixed_run/stdout.log',
                    'model_check_result': 'model_run/result.json', 'fixed_check_result': 'fixed_run/result.json',
                },
            }
            (root / 'case.json').write_text(json.dumps(manifest))
            r = subprocess.run([sys.executable, str(ROOT / 'scripts/case_check.py'), str(root / 'case.json')],
                               capture_output=True, text=True)
            res = json.loads(r.stdout)
            self.assertTrue(res['inventory_complete'], res['errors'])
            self.assertEqual(res['warnings'], [])


if __name__ == '__main__':
    unittest.main()
