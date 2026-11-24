#!/usr/bin/env python3
"""Evidence inventory, not semantic certification. Paths relative to manifest."""
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


def check(path: pathlib.Path) -> dict:
    data = json.loads(path.read_text())
    root = path.resolve().parent
    claim = data.get('claim')
    errors: list[str] = []
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
