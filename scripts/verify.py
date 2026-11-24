#!/usr/bin/env python3
"""Conservative evidence collector; not a semantic proof certifier.

Exit codes for `run`:
  0  the tool ran and reported no failure (still requires semantic review)
  1  the tool output shows the property is not established: a violation,
     counterexample, failing test, or (Lean) reliance on sorry/non-standard axioms
  2  tool missing, timeout, unrecognized failure, or input file changed
  3  the tool rejected the input or arguments (parse/type error, unknown name)
"""
import argparse
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

TOOLS = ('z3', 'cvc5', 'quint', 'verus', 'kani', 'lean')
STANDARD_LEAN_AXIOMS = {'propext', 'Classical.choice', 'Quot.sound'}
EXIT = {'clean': 0, 'violation_reported': 1, 'untrusted_axioms': 1, 'input_error': 3}

# Output signatures observed with Quint 0.34, Kani 0.68, Verus 0.2026.05, Lean 4.36,
# Z3 5.4 and cvc5 1.4. They are heuristics: unmatched failures become `unrecognized`.
QUINT_VIOLATION = (r'^\[violation\]', r'error: Invariant violated', r'error: found a counterexample', r'error: Tests failed')
QUINT_INPUT = (r'\[QNT\d+\]', r'error: (parsing|typechecking|Typecheck) failed', r'error: Argument error', r'no tests matched')
KANI_VIOLATION = (r'VERIFICATION:- FAILED', r'Verification failed for')
KANI_INPUT = (r'Failed to match the following harness', r'kani-compiler exited', r'error\[E\d+\]', r'error: aborting due to')
LEAN_INPUT = (r'error: unexpected ', r'error: unknown (identifier|constant|namespace)', r'error: expected ', r'error: unknown module prefix')


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def needs_property(args: argparse.Namespace) -> bool:
    return not (args.backend == 'quint' and args.quint_mode in ('typecheck', 'test'))


def command(args: argparse.Namespace, input_path: pathlib.Path, out_dir: pathlib.Path) -> list[str]:
    f = str(input_path)
    if args.backend == 'z3':
        return ['z3', '-smt2', f]
    if args.backend == 'cvc5':
        return ['cvc5', '--lang=smt2', '--incremental', '--produce-models', f]
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


def _matches(patterns: tuple[str, ...], lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if any(re.search(p, line) for p in patterns)]


def observe(backend: str, rc: int, stdout: str, stderr: str, prop: str | None = None) -> dict:
    """Machine-readable signals from tool output. Not a semantic verdict."""
    lines = (stdout + '\n' + stderr).splitlines()
    obs: dict = {'outcome': None, 'signals': [], 'warnings': []}

    def done(outcome: str, signals: list[str]) -> dict:
        obs['outcome'] = outcome
        obs['signals'] = signals[:20]
        return obs

    if backend in ('z3', 'cvc5'):
        obs['smt_results'] = [l.strip() for l in stdout.splitlines() if l.strip() in ('sat', 'unsat', 'unknown')]
        errors = [l.strip() for l in stdout.splitlines() if l.strip().startswith('(error')]
        if errors:
            return done('input_error', errors)
        if 'unknown' in obs['smt_results']:
            obs['warnings'].append('solver returned unknown')
        return done('clean' if rc == 0 else 'unrecognized', [])

    if backend == 'quint':
        if hits := _matches(QUINT_VIOLATION, lines):
            return done('violation_reported', hits)
        if hits := _matches(QUINT_INPUT, lines):
            return done('input_error', hits)
        return done('clean' if rc == 0 else 'unrecognized', _matches((r'^\[ok\]', r'passing', r'failing'), lines))

    if backend == 'kani':
        summary = _matches((r'successfully verified harness',), lines)
        if hits := _matches(KANI_VIOLATION, lines):
            return done('violation_reported', hits + summary)
        if rc != 0 and (hits := _matches(KANI_INPUT, lines)):
            return done('input_error', hits)
        return done('clean' if rc == 0 else 'unrecognized', summary)

    if backend == 'verus':
        try:
            vr = json.loads(stdout)['verification-results']
        except (ValueError, KeyError, TypeError):
            vr = None
        errors = _matches((r'^error',), stderr.splitlines())
        if vr is None:
            return done('clean' if rc == 0 else 'unrecognized', errors)
        obs['verus'] = {k: vr.get(k) for k in ('success', 'verified', 'errors', 'encountered-error')}
        if vr.get('errors', 0) > 0:
            return done('violation_reported', errors)
        if vr.get('encountered-error') or rc != 0:
            return done('input_error', errors)
        return done('clean', [])

    # lean
    axioms: dict[str, list[str]] = {}
    for m in re.finditer(r"^'([^']+)' (?:does not depend on any axioms|depends on axioms: \[([^\]]*)\])", stdout, re.M):
        axioms[m.group(1)] = sorted(a.strip() for a in (m.group(2) or '').split(',') if a.strip())
    obs['lean_axioms'] = axioms
    untrusted = sorted({a for used in axioms.values() for a in used} - STANDARD_LEAN_AXIOMS)
    if untrusted:
        obs['warnings'].append('non-standard axioms: ' + ', '.join(untrusted))
    if prop and not any(name == prop or name.endswith('.' + prop) for name in axioms):
        obs['warnings'].append(f"no '#print axioms {prop}' output; axiom usage of the claimed theorem is unchecked")
    errors = _matches((r'error:',), lines)
    if errors:
        if _matches(LEAN_INPUT, errors):
            return done('input_error', errors)
        return done('violation_reported', errors)
    if untrusted:
        return done('untrusted_axioms', ['non-standard axioms: ' + ', '.join(untrusted)])
    return done('clean' if rc == 0 else 'unrecognized', [])


def detect() -> dict:
    found = {}
    for tool in TOOLS:
        path = shutil.which(tool)
        entry = {'path': path, 'usable': False, 'version': None}
        if path:
            rc, out, err, timed = invoke([path, '--version'], 30, '.')
            text = (out or err).decode(errors='replace').strip()
            entry['usable'] = rc == 0 and not timed
            entry['version'] = text.splitlines()[0] if text else None
            if not entry['usable']:
                entry['error'] = 'timeout' if timed else (err or out).decode(errors='replace').strip()[:300]
        found[tool] = entry
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='action', required=True)
    sub.add_parser('detect', help='Locate each verifier and check that `--version` runs')

    r = sub.add_parser('run')
    r.add_argument('backend', choices=TOOLS)
    r.add_argument('file', type=pathlib.Path)
    r.add_argument('--property', help='Invariant (Quint run/verify), harness (Kani) or record label. '
                   'Not accepted for quint typecheck/test; use --quint-match.')
    r.add_argument('--bound', type=int, default=10)
    r.add_argument('--timeout', type=int, default=120)
    r.add_argument('--out', type=pathlib.Path, required=True)
    r.add_argument('--cwd', type=pathlib.Path, default=None,
                   help='Working directory for the tool (default: OUT/work, so build outputs stay inside OUT). '
                        'Set it to the project root for Lake/Cargo projects.')
    r.add_argument('--quint-mode', choices=('typecheck', 'test', 'run', 'verify'), default='verify')
    r.add_argument('--quint-backend', choices=('apalache', 'tlc'), default='apalache')
    r.add_argument('--seed', type=int, default=42)
    r.add_argument('--samples', type=int, default=100)
    r.add_argument('--quint-itf', action='store_true', help='Export ITF trace to out/trace.itf.json for run/verify')
    r.add_argument('--quint-match', default=None, help='Test name filter for quint test (--match)')

    args = ap.parse_args()
    if args.action == 'detect':
        print(json.dumps(detect(), indent=2))
        return 0

    if needs_property(args):
        if not args.property or not args.property.strip():
            ap.error(f'--property is required for {args.backend}')
    elif args.property is not None:
        ap.error(f'--property is ignored by quint {args.quint_mode}; use --quint-match for test selection')
    if args.samples < 1 or args.seed < 0 or args.bound < 0 or args.timeout < 1 or not args.file.is_file():
        ap.error('invalid bound, timeout, seed, samples or input file')

    input_path = args.file.resolve()
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=False)
    if args.cwd is None:
        cwd = out_dir / 'work'
        cwd.mkdir()
    else:
        cwd = args.cwd.resolve()

    before = digest(input_path)
    cmd = command(args, input_path, out_dir)
    start = time.monotonic()

    executable = shutil.which(cmd[0])
    version = None
    if executable:
        cmd[0] = executable
        vc, vo, ve, vt = invoke([executable, '--version'], min(15, args.timeout), cwd)
        version = {
            'exit_code': vc,
            'stdout': vo.decode(errors='replace'),
            'stderr': ve.decode(errors='replace'),
            'timeout': vt,
        }
        rc, stdout, stderr, timed = invoke(cmd, args.timeout, cwd)
    else:
        rc, stdout, stderr, timed = None, b'', b'tool not found', False

    after = digest(input_path) if input_path.is_file() else None

    (out_dir / 'stdout.log').write_bytes(stdout)
    (out_dir / 'stderr.log').write_bytes(stderr)

    if timed:
        observed = {'outcome': 'timeout', 'signals': [], 'warnings': []}
    elif rc is None:
        observed = {'outcome': 'tool_missing', 'signals': [stderr.decode(errors='replace')], 'warnings': []}
    else:
        observed = observe(args.backend, rc, stdout.decode(errors='replace'), stderr.decode(errors='replace'), args.property)

    outcome = observed['outcome']
    status = {'timeout': 'TIMEOUT', 'tool_missing': 'TOOL_ERROR', 'input_error': 'TOOL_ERROR',
              'unrecognized': 'TOOL_ERROR'}.get(outcome, 'UNKNOWN')

    logs = {name: digest(out_dir / name) for name in ('stdout.log', 'stderr.log')}
    itf_path = out_dir / 'trace.itf.json'
    if itf_path.is_file():
        logs['trace.itf.json'] = digest(itf_path)

    is_quint = args.backend == 'quint'
    result = {
        'schema_version': 2,
        'backend': args.backend,
        'property': args.property,
        'input': str(input_path),
        'input_sha256': before,
        'input_changed': before != after,
        'command': cmd,
        'cwd': str(cwd),
        'version': version,
        'exit_code': rc,
        'status': status,
        'observed': observed,
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
    if before != after:
        return 2
    return EXIT.get(outcome, 2)


if __name__ == '__main__':
    sys.exit(main())
