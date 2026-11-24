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
