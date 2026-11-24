import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest

P = pathlib.Path(__file__).resolve().parents[1] / 'scripts/case_check.py'
s = importlib.util.spec_from_file_location('case_check', P)
c = importlib.util.module_from_spec(s)
s.loader.exec_module(c)


class Case(unittest.TestCase):
    def _base_manifest(self, claim='MODEL_ONLY'):
        return dict(
            property_id='P1',
            property='safe',
            source_revision='abc',
            assumptions=[],
            exclusions=[],
            tradeoffs=[],
            mapping=[
                dict(
                    abstract_action='a',
                    source_symbol='f',
                    concrete_inputs='1',
                    observable_effect='r',
                )
            ],
            claim=claim,
            evidence={},
        )

    def test_inventory(self):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            p = root / 'case.json'
            d = self._base_manifest('MODEL_ONLY')
            for k in c.REQUIRED['MODEL_ONLY']:
                (root / k).write_text(k)
                d['evidence'][k] = k
            p.write_text(json.dumps(d))
            self.assertTrue(c.check(p)['inventory_complete'])

            d['claim'] = 'REPRODUCED'
            p.write_text(json.dumps(d))
            self.assertFalse(c.check(p)['inventory_complete'])

            d['claim'] = 'MODEL_ONLY'
            d['evidence']['trace'] = '../outside'
            p.write_text(json.dumps(d))
            self.assertFalse(c.check(p)['inventory_complete'])

    def test_model_mismatch_and_fix_checks(self):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            p = root / 'case.json'

            d = self._base_manifest('MODEL_MISMATCH')
            for k in c.REQUIRED['MODEL_MISMATCH']:
                (root / k).write_text(k)
                d['evidence'][k] = k
            p.write_text(json.dumps(d))
            self.assertTrue(c.check(p)['inventory_complete'])

            d = self._base_manifest('FIX_REPLAYED')
            for k in c.REQUIRED['FIX_REPLAYED']:
                (root / k).write_text(k)
                d['evidence'][k] = k
            # Same content for model and fixed_model must fail
            (root / 'fixed_model').write_text('model')
            p.write_text(json.dumps(d))
            res = c.check(p)
            self.assertFalse(res['inventory_complete'])
            self.assertIn('original and fixed models must differ', res['errors'])

            (root / 'fixed_model').write_text('fixed_model')
            p.write_text(json.dumps(d))
            self.assertTrue(c.check(p)['inventory_complete'])

    def test_empty(self):
        with tempfile.TemporaryDirectory() as t:
            p = pathlib.Path(t) / 'case.json'
            p.write_text('{}')
            self.assertFalse(c.check(p)['inventory_complete'])

    def _result(self, root, name, model_text, outcome, **over):
        d = root / name
        d.mkdir()
        (d / 'stdout.log').write_text(outcome)
        (d / 'stderr.log').write_text('')
        res = dict(schema_version=3, backend='quint', property='safe', bound=5, quint_mode='verify',
                   quint_backend='apalache', input_changed=False,
                   input_sha256=hashlib.sha256(model_text.encode()).hexdigest(),
                   observed={'outcome': outcome},
                   logs={n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in ('stdout.log', 'stderr.log')})
        res.update(over)
        (d / 'result.json').write_text(json.dumps(res))
        return f'{name}/result.json'

    def _fix_case(self, root, **fixed_over):
        d = self._base_manifest('FIX_REPLAYED')
        for k in c.REQUIRED['FIX_REPLAYED']:
            (root / k).write_text(k)
            d['evidence'][k] = k
        d['evidence']['model_check_result'] = self._result(root, 'model_run', 'model', 'violation_reported')
        d['evidence']['fixed_check_result'] = self._result(root, 'fixed_run', 'fixed_model', 'clean', **fixed_over)
        p = root / 'case.json'
        p.write_text(json.dumps(d))
        return p

    def test_result_cross_check_passes(self):
        with tempfile.TemporaryDirectory() as t:
            res = c.check(self._fix_case(pathlib.Path(t)))
            self.assertTrue(res['inventory_complete'], res['errors'])
            self.assertEqual(res['warnings'], [])

    def test_result_cross_check_failures(self):
        cases = [
            ({'observed': {'outcome': 'violation_reported'}}, 'fixed_check_result: expected outcome clean'),
            ({'bound': 3}, 'model and fixed checks differ in bound'),
            ({'property': 'other'}, 'model and fixed checks differ in property'),
            ({'input_sha256': '0' * 64}, 'fixed_check_result: input_sha256 does not match evidence fixed_model'),
            ({'input_changed': True}, 'fixed_check_result: input changed during the check'),
            ({'logs': {'../x': 'y'}}, "fixed_check_result: invalid log name '../x'"),
        ]
        for over, msg in cases:
            with self.subTest(msg), tempfile.TemporaryDirectory() as t:
                res = c.check(self._fix_case(pathlib.Path(t), **over))
                self.assertFalse(res['inventory_complete'])
                self.assertTrue(any(e.startswith(msg) for e in res['errors']), res['errors'])

    def test_result_log_tampering_detected(self):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            p = self._fix_case(root)
            (root / 'model_run' / 'stdout.log').write_text('edited')
            res = c.check(p)
            self.assertIn('model_check_result: log stdout.log missing or does not match its recorded sha256', res['errors'])

    def test_missing_results_warn(self):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            d = self._base_manifest('MODEL_ONLY')
            for k in c.REQUIRED['MODEL_ONLY']:
                (root / k).write_text(k)
                d['evidence'][k] = k
            p = root / 'case.json'
            p.write_text(json.dumps(d))
            res = c.check(p)
            self.assertTrue(res['inventory_complete'])
            self.assertIn('no model_check_result', res['warnings'][0])
