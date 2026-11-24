import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

P = pathlib.Path(__file__).resolve().parents[1] / 'scripts/verify.py'
spec = importlib.util.spec_from_file_location('verify', P)
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class Runner(unittest.TestCase):
    def test_timeout(self):
        self.assertTrue(v.invoke([sys.executable, '-c', 'import time; time.sleep(2)'], 0.05, '.')[3])

    def test_missing(self):
        self.assertIsNone(v.invoke(['/nonexistent/formal-verify'], 1, '.')[0])

    def test_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            p = d / 'model.smt2'
            p.write_text('(check-sat)')
            out = d / 'evidence'
            fake = d / 'z3'
            fake.write_text('#!/bin/sh\nprintf "unsat\\n"\n')
            fake.chmod(0o755)
            env = dict(os.environ, PATH=str(d) + os.pathsep + os.environ['PATH'])
            result = subprocess.run(
                [sys.executable, str(P), 'run', 'z3', str(p), '--property', 'example', '--out', str(out)],
                env=env,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0)
            data = json.loads((out / 'result.json').read_text())
            self.assertEqual(data['status'], 'UNKNOWN')
            self.assertTrue(data['review_required'])
            self.assertEqual(data['logs']['stdout.log'], v.digest(out / 'stdout.log'))

    def test_quint_run_metadata_and_itf(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            p = d / 'model.qnt'
            p.write_text('module m {}')
            out = d / 'evidence'
            fake = d / 'quint'
            fake.write_text(
                '#!/bin/sh\n'
                'for arg in "$@"; do\n'
                '  case "$arg" in\n'
                '    --out-itf=*) printf "{}" > "${arg#--out-itf=}" ;;\n'
                '  esac\n'
                'done\n'
                'printf "ok\\n"\n'
            )
            fake.chmod(0o755)
            env = dict(os.environ, PATH=str(d) + os.pathsep + os.environ['PATH'])
            result = subprocess.run(
                [
                    sys.executable,
                    str(P),
                    'run',
                    'quint',
                    str(p),
                    '--quint-mode',
                    'run',
                    '--property',
                    'safe',
                    '--seed',
                    '7',
                    '--samples',
                    '25',
                    '--quint-itf',
                    '--out',
                    str(out),
                ],
                env=env,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0)
            data = json.loads((out / 'result.json').read_text())
            self.assertEqual(data['quint_seed'], 7)
            self.assertEqual(data['quint_samples'], 25)
            self.assertIn('trace.itf.json', data['logs'])

    def test_detect(self):
        found = json.loads(subprocess.check_output([sys.executable, str(P), 'detect']))
        self.assertEqual(set(found), set(v.TOOLS))
        for entry in found.values():
            self.assertEqual({'path', 'usable', 'version'} - set(entry), set())

    def test_detect_reports_unusable_tool(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            fake = d / 'lean'
            fake.write_text('#!/bin/sh\necho "error: no default toolchain configured" >&2\nexit 1\n')
            fake.chmod(0o755)
            env = dict(os.environ, PATH=str(d) + os.pathsep + os.environ['PATH'])
            found = json.loads(subprocess.check_output([sys.executable, str(P), 'detect'], env=env))
            self.assertEqual(found['lean']['path'], str(fake))
            self.assertFalse(found['lean']['usable'])
            self.assertIn('no default toolchain', found['lean']['error'])

    def _run(self, d, *argv):
        out = d / 'evidence'
        r = subprocess.run([sys.executable, str(P), 'run', *argv, '--out', str(out)], capture_output=True, text=True)
        return r, out

    def test_default_cwd_is_inside_out(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            fake = d / 'z3'
            fake.write_text('#!/bin/sh\ntouch side_effect\nprintf "unsat\\n"\n')
            fake.chmod(0o755)
            p = d / 'm.smt2'
            p.write_text('(check-sat)')
            env = dict(os.environ, PATH=str(d) + os.pathsep + os.environ['PATH'])
            out = d / 'evidence'
            subprocess.run([sys.executable, str(P), 'run', 'z3', str(p), '--property', 'x', '--out', str(out)],
                           env=env, cwd=d, capture_output=True, check=True)
            self.assertTrue((out / 'work' / 'side_effect').is_file())
            self.assertFalse((d / 'side_effect').exists())

    def test_quint_test_rejects_property(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            p = d / 'm.qnt'
            p.write_text('module m {}')
            r, out = self._run(d, 'quint', str(p), '--quint-mode', 'test', '--property', 'safe')
            self.assertEqual(r.returncode, 2)
            self.assertIn('--quint-match', r.stderr)
            self.assertFalse(out.exists())

    def test_property_required_for_verify(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            p = d / 'm.smt2'
            p.write_text('(check-sat)')
            r, _ = self._run(d, 'z3', str(p))
            self.assertEqual(r.returncode, 2)
            self.assertIn('--property is required', r.stderr)

    def test_exit_code_follows_outcome(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            p = d / 'm.qnt'
            p.write_text('module m {}')
            fake = d / 'quint'
            fake.write_text('#!/bin/sh\nprintf "[violation] Found an issue\\n"\necho "error: Invariant violated" >&2\nexit 1\n')
            fake.chmod(0o755)
            env = dict(os.environ, PATH=str(d) + os.pathsep + os.environ['PATH'])
            out = d / 'evidence'
            r = subprocess.run([sys.executable, str(P), 'run', 'quint', str(p), '--property', 'safe', '--out', str(out)],
                               env=env, capture_output=True)
            self.assertEqual(r.returncode, 1)
            data = json.loads((out / 'result.json').read_text())
            self.assertEqual(data['observed']['outcome'], 'violation_reported')
            self.assertEqual(data['status'], 'UNKNOWN')


class Observe(unittest.TestCase):
    """Signatures captured from real tool output (see verify.py header for versions)."""

    def check(self, backend, rc, stdout, stderr, outcome):
        self.assertEqual(v.observe(backend, rc, stdout, stderr)['outcome'], outcome)

    def test_quint(self):
        self.check('quint', 0, '[ok] No violation found (2899ms).\n', '', 'clean')
        self.check('quint', 1, '[violation] Found an issue (10431ms).\n  ❌ safe\n', 'error: found a counterexample\n', 'violation_reported')
        self.check('quint', 1, '', 'error: Tests failed\n', 'violation_reported')
        self.check('quint', 1, '', "error: [QNT404] Name 'saef' not found (given with --invariant)\nerror: Argument error\n", 'input_error')
        self.check('quint', 1, '', 'error: parsing failed\n', 'input_error')
        self.check('quint', 1, '', "error: no tests matched --match 'x'.\n", 'input_error')
        self.check('quint', 1, '', 'segfault\n', 'unrecognized')

    def test_smt(self):
        o = v.observe('z3', 0, 'sat\nunsat\n', '')
        self.assertEqual((o['outcome'], o['smt_results']), ('clean', ['sat', 'unsat']))
        self.check('z3', 1, '(error "line 2 column 0: invalid expression, unexpected input")\n', '', 'input_error')
        self.check('cvc5', 0, 'sat\n(error "cannot get model unless model generation is enabled")\n', '', 'input_error')
        self.assertIn('solver returned unknown', v.observe('z3', 0, 'unknown\n', '')['warnings'])

    def test_kani(self):
        self.check('kani', 0, 'VERIFICATION:- SUCCESSFUL\nComplete - 1 successfully verified harnesses, 0 failures, 1 total.\n', '', 'clean')
        self.check('kani', 1, 'VERIFICATION:- FAILED\nVerification failed for - check\n', 'warning: 1 warning emitted\n', 'violation_reported')
        self.check('kani', 1, 'error: Failed to match the following harness(es):\nnope\n', '', 'input_error')
        self.check('kani', 1, 'error: .../kani-compiler exited with status exit status: 101\n', 'error: aborting due to 2 previous errors\n', 'input_error')

    def test_verus(self):
        def out(errors, encountered):
            return json.dumps({'verification-results': {'success': not encountered, 'verified': 1, 'errors': errors, 'encountered-error': encountered}})
        self.check('verus', 0, out(0, False), '', 'clean')
        self.check('verus', 1, out(1, True), 'error: possible arithmetic underflow/overflow\n', 'violation_reported')
        self.check('verus', 1, out(0, True), 'error: expected an expression\n', 'input_error')
        self.check('verus', 1, 'not json', '', 'unrecognized')

    def test_lean(self):
        self.check('lean', 0, "'add_comm_example' does not depend on any axioms\n", '', 'clean')
        self.check('lean', 1, 'LF.lean:2:2: error: omega could not prove the goal:\n', '', 'violation_reported')
        o = v.observe('lean', 1, "LS.lean:1:8: error: declaration uses `sorry`\n't' depends on axioms: [sorryAx]\n", '')
        self.assertEqual(o['outcome'], 'violation_reported')
        self.assertIn('non-standard axioms: sorryAx', o['warnings'])
        self.check('lean', 1, 'A.lean:1:5: error: unexpected token \'theorem\'\n', '', 'input_error')
        o = v.observe('lean', 0, "'u' depends on axioms: [bad, propext]\n", '')
        self.assertEqual((o['outcome'], o['warnings']), ('clean', ['non-standard axioms: bad']))


if __name__ == '__main__':
    unittest.main()
