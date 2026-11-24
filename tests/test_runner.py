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


class ProcessAndProject(unittest.TestCase):
    def test_timeout_kills_grandchildren(self):
        with tempfile.TemporaryDirectory() as t:
            pid_file = pathlib.Path(t) / 'pid'
            script = pathlib.Path(t) / 'spawn.sh'
            script.write_text('#!/bin/sh\nsleep 60 &\necho $! > "$1"\nsleep 60\n')
            script.chmod(0o755)
            r = v.invoke([str(script), str(pid_file)], 0.5, '.')
            self.assertTrue(r[3])
            pid = int(pid_file.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_leftover_background_process_is_killed(self):
        with tempfile.TemporaryDirectory() as t:
            pid_file = pathlib.Path(t) / 'pid'
            script = pathlib.Path(t) / 'bg.sh'
            script.write_text('#!/bin/sh\nsleep 60 > /dev/null 2>&1 &\necho $! > "$1"\n')
            script.chmod(0o755)
            rc, _, _, timed, leftover = v.invoke([str(script), str(pid_file)], 10, '.')
            self.assertEqual((rc, timed, leftover), (0, False, True))
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)

    def _crate(self, d, cargo_body):
        proj = d / 'crate'
        (proj / 'src').mkdir(parents=True)
        (proj / 'Cargo.toml').write_text('[package]\nname = "c"\nversion = "0.1.0"\n')
        (proj / 'src' / 'lib.rs').write_text('pub fn f() {}\n')
        bindir = d / 'bin'
        bindir.mkdir()
        cargo = bindir / 'cargo'
        cargo.write_text('#!/bin/sh\n' + cargo_body)
        cargo.chmod(0o755)
        env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'])
        return proj, env

    def _run_project(self, d, proj, env, backend='kani'):
        out = d / 'evidence'
        r = subprocess.run([sys.executable, str(P), 'run', backend, '--project', str(proj), '--property', 'h',
                            '--out', str(out)], env=env, capture_output=True, text=True)
        return r, json.loads((out / 'result.json').read_text())

    def test_project_mode_isolates_target_and_reports_changes(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            body = ('echo "$CARGO_TARGET_DIR" > "$PWD/../target_dir"\n'
                    'echo "VERIFICATION:- SUCCESSFUL"\n'
                    'echo "Complete - 1 successfully verified harnesses, 0 failures, 1 total."\n')
            proj, env = self._crate(d, body)
            r, data = self._run_project(d, proj, env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(data['command'][1:], ['kani', '--harness', 'h'])
            self.assertEqual((d / 'target_dir').read_text().strip(), str((d / 'evidence' / 'work' / 'target').resolve()))
            self.assertEqual(data['project']['file_count'], 2)
            self.assertFalse(data['input_changed'])

    def test_project_mode_detects_modified_source(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            proj, env = self._crate(d, 'echo "// edited" >> src/lib.rs\ntouch NEW.txt\necho "VERIFICATION:- SUCCESSFUL"\n')
            r, data = self._run_project(d, proj, env)
            self.assertEqual(r.returncode, 2)
            self.assertTrue(data['input_changed'])
            self.assertEqual(data['project']['changes'], {'modified_or_deleted': ['src/lib.rs'], 'created': ['NEW.txt']})

    def test_project_argument_validation(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            f = d / 'm.smt2'
            f.write_text('(check-sat)')
            cases = [
                (['z3', str(f), '--project', str(d), '--property', 'x'], 'supported for kani, verus and lean'),
                (['kani', '--project', str(d), '--property', 'x'], 'has no Cargo.toml'),
                (['lean', '--project', str(d), '--property', 'x'], 'has no lakefile.toml'),
                (['kani', '--property', 'x'], 'input file is missing'),
            ]
            for i, (argv, msg) in enumerate(cases):
                r = subprocess.run([sys.executable, str(P), 'run', *argv, '--out', str(d / f'o{i}')],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 2)
                self.assertIn(msg, r.stderr)


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

    def test_verus_cargo_stream(self):
        one = json.dumps({'verification-results': {'success': True, 'verified': 2354, 'errors': 0, 'encountered-error': False}})
        two = json.dumps({'verification-results': {'success': False, 'verified': 0, 'errors': 1, 'encountered-error': True}})
        o = v.observe('verus', 101, one + '\n' + two, 'error: postcondition not satisfied\n')
        self.assertEqual(o['outcome'], 'violation_reported')
        self.assertEqual((o['verus']['crates'], o['verus']['verified'], o['verus']['errors']), (2, 2354, 1))
        self.check('verus', 101, '', 'error: could not compile `c` (lib) due to 1 previous error\n', 'input_error')

    def test_lean_lake_axiom_format(self):
        out = "info: LeanLake/Midpoint.lean:7:0: 'midpoint_le_max' depends on axioms: [propext, Quot.sound]\n"
        o = v.observe('lean', 0, out, '', 'midpoint_le_max')
        self.assertEqual((o['outcome'], o['warnings'], o['lean_axioms']),
                         ('clean', [], {'midpoint_le_max': ['Quot.sound', 'propext']}))

    def test_lean(self):
        self.check('lean', 0, "'add_comm_example' does not depend on any axioms\n", '', 'clean')
        self.check('lean', 1, 'LF.lean:2:2: error: omega could not prove the goal:\n', '', 'violation_reported')
        o = v.observe('lean', 1, "LS.lean:1:8: error: declaration uses `sorry`\n't' depends on axioms: [sorryAx]\n", '')
        self.assertEqual(o['outcome'], 'violation_reported')
        self.assertIn('non-standard axioms: sorryAx', o['warnings'])
        self.check('lean', 1, 'A.lean:1:5: error: unexpected token \'theorem\'\n', '', 'input_error')
        o = v.observe('lean', 0, "'u' depends on axioms: [bad, propext]\n", '', 'u')
        self.assertEqual((o['outcome'], o['warnings']), ('untrusted_axioms', ['non-standard axioms: bad']))
        o = v.observe('lean', 0, "'Foo.t' depends on axioms: [propext, Classical.choice, Quot.sound]\n", '', 't')
        self.assertEqual((o['outcome'], o['warnings']), ('clean', []))
        o = v.observe('lean', 0, '', '', 't')
        self.assertEqual(o['outcome'], 'clean')
        self.assertIn("no '#print axioms t' output", o['warnings'][0])


if __name__ == '__main__':
    unittest.main()
