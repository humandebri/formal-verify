#!/usr/bin/env python3
"""Conservative evidence collector; not a semantic proof certifier."""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import time

TOOLS = ('z3', 'cvc5', 'quint', 'verus', 'kani', 'lean')


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args: argparse.Namespace, input_path: pathlib.Path, out_dir: pathlib.Path) -> list[str]:
    f = str(input_path)
    if args.backend == 'z3':
        return ['z3', '-smt2', f]
    if args.backend == 'cvc5':
        return ['cvc5', '--lang=smt2', '--incremental', f]
    if args.backend == 'quint':
        cmd = ['quint', args.quint_mode, f]
        if args.quint_mode in ('run', 'verify'):
            cmd += [f'--invariant={args.property}', f'--max-steps={args.bound}']
            if args.quint_itf:
                cmd += [f'--out-itf={out_dir / "trace.itf.json"}']
        if args.quint_mode == 'verify':
            cmd += [f'--backend={args.quint_backend}']
        if args.quint_mode == 'run':
            cmd += [f'--seed={args.seed}', f'--max-samples={args.samples}']
        if args.quint_mode == 'test' and args.quint_match:
            cmd += [f'--match={args.quint_match}']
        return cmd
    if args.backend == 'verus':
        return ['verus', '--output-json', f]
    if args.backend == 'kani':
        return ['kani', f, '--harness', args.property]
    return ['lean', '-DwarningAsError=true', f]


def invoke(cmd: list[str], timeout: float, cwd: pathlib.Path | str):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout, check=False)
        return r.returncode, r.stdout, r.stderr, False
    except subprocess.TimeoutExpired as e:
        return None, e.stdout or b'', e.stderr or b'', True
    except OSError as e:
        return None, b'', str(e).encode(), False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='action', required=True)
    sub.add_parser('detect')

    r = sub.add_parser('run')
    r.add_argument('backend', choices=TOOLS)
    r.add_argument('file', type=pathlib.Path)
    r.add_argument('--property', required=True)
    r.add_argument('--bound', type=int, default=10)
    r.add_argument('--timeout', type=int, default=120)
    r.add_argument('--out', type=pathlib.Path, required=True)
    r.add_argument('--cwd', type=pathlib.Path, default=pathlib.Path.cwd())
    r.add_argument('--quint-mode', choices=('typecheck', 'test', 'run', 'verify'), default='verify')
    r.add_argument('--quint-backend', choices=('apalache', 'tlc'), default='apalache')
    r.add_argument('--seed', type=int, default=42)
    r.add_argument('--samples', type=int, default=100)
    r.add_argument('--quint-itf', action='store_true', help='Export ITF trace to out/trace.itf.json for run/verify')
    r.add_argument('--quint-match', default=None, help='Test name filter for quint test (--match)')

    args = ap.parse_args()
    if args.action == 'detect':
        print(json.dumps({t: shutil.which(t) for t in TOOLS}, indent=2))
        return 0

    if (
        args.samples < 1
        or args.seed < 0
        or args.bound < 0
        or args.timeout < 1
        or not args.property.strip()
        or not args.file.is_file()
    ):
        ap.error('invalid bound, timeout, property or input file')

    input_path = args.file.resolve()
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=False)

    before = digest(input_path)
    cmd = command(args, input_path, out_dir)
    start = time.monotonic()

    executable = shutil.which(cmd[0])
    version = None
    if executable:
        cmd[0] = executable
        vc, vo, ve, vt = invoke([executable, '--version'], min(15, args.timeout), args.cwd)
        version = {
            'exit_code': vc,
            'stdout': vo.decode(errors='replace'),
            'stderr': ve.decode(errors='replace'),
            'timeout': vt,
        }
        rc, stdout, stderr, timed = invoke(cmd, args.timeout, args.cwd)
    else:
        rc, stdout, stderr, timed = None, b'', b'tool not found', False

    after = digest(input_path) if input_path.is_file() else None
    status = 'TIMEOUT' if timed else 'TOOL_ERROR' if rc is None else 'UNKNOWN'

    (out_dir / 'stdout.log').write_bytes(stdout)
    (out_dir / 'stderr.log').write_bytes(stderr)

    logs = {name: digest(out_dir / name) for name in ('stdout.log', 'stderr.log')}
    itf_path = out_dir / 'trace.itf.json'
    if itf_path.is_file():
        logs['trace.itf.json'] = digest(itf_path)

    is_quint = args.backend == 'quint'
    result = {
        'schema_version': 1,
        'backend': args.backend,
        'property': args.property,
        'input': str(input_path),
        'input_sha256': before,
        'input_changed': before != after,
        'command': cmd,
        'cwd': str(args.cwd.resolve()),
        'version': version,
        'exit_code': rc,
        'status': status,
        'review_required': True,
        'elapsed_seconds': round(time.monotonic() - start, 3),
        'bound': args.bound if is_quint and args.quint_mode in ('run', 'verify') else None,
        'quint_mode': args.quint_mode if is_quint else None,
        'quint_backend': args.quint_backend if is_quint and args.quint_mode == 'verify' else None,
        'quint_seed': args.seed if is_quint and args.quint_mode == 'run' else None,
        'quint_samples': args.samples if is_quint and args.quint_mode == 'run' else None,
        'logs': logs,
    }
    (out_dir / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 2 if status != 'UNKNOWN' or rc != 0 or before != after else 0


if __name__ == '__main__':
    sys.exit(main())
