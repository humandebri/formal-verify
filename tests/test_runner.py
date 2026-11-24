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
        self.assertEqual(set(json.loads(subprocess.check_output([sys.executable, str(P), 'detect']))), set(v.TOOLS))


if __name__ == '__main__':
    unittest.main()
