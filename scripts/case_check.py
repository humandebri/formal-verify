#!/usr/bin/env python3
"""Evidence inventory, not semantic certification. Paths relative to manifest.

Optional evidence `model_check_result` / `fixed_check_result` point at result.json files written by
scripts/verify.py. When present they are cross-checked: log hashes, input hashes against `model` /
`fixed_model`, the expected outcome (violation on the original model, clean on the fixed one), and
that both checks used the same backend, property, bound and mode.
"""
import argparse
import hashlib
import json
import pathlib
import sys

REQUIRED = {
    'MODEL_ONLY': {'model', 'trace', 'model_regression'},
    'MODEL_MISMATCH': {'model', 'trace', 'model_regression', 'implementation_test', 'replay_log'},
    'REPRODUCED': {'model', 'trace', 'model_regression', 'implementation_test', 'red_log'},
    'FIX_REPLAYED': {
        'model',
        'trace',
        'model_regression',
        'implementation_test',
        'red_log',
        'green_log',
        'fixed_model',
        'fixed_check_log',
    },
}


RESULT_KEYS = {'model_check_result': ('model', 'violation_reported'),
               'fixed_check_result': ('fixed_model', 'clean')}
SAME_SETTINGS = ('backend', 'property', 'bound', 'quint_mode', 'quint_backend')


def check_result(key: str, p: pathlib.Path, hashes: dict, errors: list[str]) -> dict | None:
    try:
        data = json.loads(p.read_text())
    except ValueError:
        errors.append(f'{key}: not JSON')
        return None
    if not isinstance(data, dict) or not isinstance(data.get('observed'), dict) or data.get('schema_version', 0) < 2:
        errors.append(f'{key}: not a verify.py result.json (schema_version >= 2)')
        return None
    for name, expected in (data.get('logs') or {}).items():
        if not isinstance(name, str) or pathlib.PurePath(name).name != name:
            errors.append(f'{key}: invalid log name {name!r}')
            continue
        log = p.parent / name
        if not log.is_file() or hashlib.sha256(log.read_bytes()).hexdigest() != expected:
            errors.append(f'{key}: log {name} missing or does not match its recorded sha256')
    if data.get('input_changed'):
        errors.append(f'{key}: input changed during the check')
    source, outcome = RESULT_KEYS[key]
    if data['observed'].get('outcome') != outcome:
        errors.append(f"{key}: expected outcome {outcome}, got {data['observed'].get('outcome')}")
    if source in hashes and data.get('input_sha256') != hashes[source]:
        errors.append(f'{key}: input_sha256 does not match evidence {source}')
    return data


def check(path: pathlib.Path) -> dict:
    data = json.loads(path.read_text())
    root = path.resolve().parent
    claim = data.get('claim')
    errors: list[str] = []
    warnings: list[str] = []
    hashes: dict[str, str] = {}

    if claim not in REQUIRED:
        errors.append('unknown claim')

    for key in ('property_id', 'property', 'source_revision'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append('missing ' + key)

    for key in ('assumptions', 'exclusions', 'tradeoffs'):
        if not isinstance(data.get(key), list):
            errors.append('expected list ' + key)

    mapping = data.get('mapping')
    if (
        not isinstance(mapping, list)
        or not mapping
        or any(
            not isinstance(m, dict)
            or any(
                not isinstance(m.get(k), str) or not m[k].strip()
                for k in ('abstract_action', 'source_symbol', 'concrete_inputs', 'observable_effect')
            )
            for m in mapping
        )
    ):
        errors.append('incomplete action mapping')

    evidence = data.get('evidence', {})
    if not isinstance(evidence, dict):
        evidence = {}
        errors.append('invalid evidence')

    for key in sorted(REQUIRED.get(claim, set()) - evidence.keys()):
        errors.append('missing evidence ' + key)

    for key, value in evidence.items():
        if not isinstance(value, str) or not value.strip():
            errors.append('invalid path ' + key)
            continue
        p = (root / value).resolve()
        if pathlib.Path(value).is_absolute() or not p.is_relative_to(root) or not p.is_file():
            errors.append('invalid path ' + key)
            continue
        if p.stat().st_size == 0:
            errors.append('empty evidence ' + key)
            continue
        hashes[key] = hashlib.sha256(p.read_bytes()).hexdigest()

    results = {}
    for key in RESULT_KEYS:
        if key in hashes:
            data = check_result(key, (root / evidence[key]).resolve(), hashes, errors)
            if data is not None:
                results[key] = data
    if len(results) == 2:
        a, b = results['model_check_result'], results['fixed_check_result']
        for field in SAME_SETTINGS:
            if a.get(field) != b.get(field):
                errors.append(f'model and fixed checks differ in {field}: {a.get(field)!r} vs {b.get(field)!r}')
    if claim and claim in REQUIRED and 'model_check_result' not in results:
        warnings.append('no model_check_result: the model counterexample is not machine-cross-checked')
    if claim == 'FIX_REPLAYED' and 'fixed_check_result' not in results:
        warnings.append('no fixed_check_result: the fixed model check is not machine-cross-checked')

    if claim == 'FIX_REPLAYED':
        if hashes.get('red_log') and hashes.get('red_log') == hashes.get('green_log'):
            errors.append('RED/GREEN logs must differ')
        if hashes.get('model') and hashes.get('model') == hashes.get('fixed_model'):
            errors.append('original and fixed models must differ')

    return {
        'claim': claim,
        'inventory_complete': not errors,
        'semantic_review_required': True,
        'errors': errors,
        'warnings': warnings,
        'sha256': hashes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=pathlib.Path)
    args = parser.parse_args()
    try:
        result = check(args.manifest)
    except (ValueError, OSError, TypeError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result['inventory_complete'] else 2


if __name__ == '__main__':
    sys.exit(main())
