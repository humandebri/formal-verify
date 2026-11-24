#!/usr/bin/env python3
"""Conservative evidence collector; not a semantic proof certifier.

Project mode (`--project DIR`): Kani runs `cargo kani`, Verus runs `cargo verus focus`
and Lean runs `lake lean FILE`, inside DIR. Cargo builds go to OUT/work/target.

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
import os
import pathlib
import re
import shutil
import signal
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
KANI_INPUT = (r'Failed to match the following harness', r'kani-compiler exited', r'error\[E\d+\]', r'error: aborting due to',
              r'error: could not compile', r'error: failed to (parse|load) manifest', r'could not find `Cargo.toml`')
VERUS_INPUT = (r'error: could not compile', r'error\[E\d+\]', r'error: failed to (parse|load) manifest',
               r'could not find `Cargo.toml`', r'error: no matching package')
SKIP_DIRS = {'.git', 'target', '.lake', 'node_modules', '_apalache-out', '__pycache__'}
LEAN_INPUT = (r'error: unexpected ', r'error: unknown (identifier|constant|namespace)', r'error: expected ', r'error: unknown module prefix')


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_info(path: pathlib.Path) -> dict | None:
    base = path if path.is_dir() else path.parent
    try:
        head = subprocess.run(['git', '-C', str(base), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=10)
        if head.returncode != 0:
            return None
        dirty = subprocess.run(['git', '-C', str(base), 'status', '--porcelain', '--', str(path)],
                               capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return {'head': head.stdout.strip(), 'dirty': bool(dirty.stdout.strip())}


def tree_files(root: pathlib.Path) -> dict[str, str]:
    """sha256 of every source file under root (git-tracked/untracked-not-ignored when in a repo)."""
    names = None
    try:
        r = subprocess.run(['git', '-C', str(root), 'ls-files', '-co', '--exclude-standard', '-z'],
                           capture_output=True, timeout=60)
        if r.returncode == 0:
            names = [n for n in r.stdout.decode(errors='replace').split('\0') if n]
    except (OSError, subprocess.TimeoutExpired):
        pass
    if names is None:
        names = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            names += [str(pathlib.Path(dirpath, f).relative_to(root)) for f in filenames]
    out = {}
    for n in sorted(names):
        f = root / n
        if f.is_file() and not any(part in SKIP_DIRS for part in pathlib.Path(n).parts):
            out[n] = digest(f)
    return out


def tree_digest(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def needs_property(args: argparse.Namespace) -> bool:
    return not (args.backend == 'quint' and args.quint_mode in ('typecheck', 'test'))


def command(args: argparse.Namespace, input_path: pathlib.Path | None, out_dir: pathlib.Path) -> list[str]:
    f = str(input_path) if input_path else ''
    if args.project:
        if args.backend == 'kani':
            return ['cargo', 'kani', '--harness', args.property]
        if args.backend == 'verus':
            return ['cargo', 'verus', 'focus', '--', '--output-json']
        return ['lake', 'lean', f, '--', '-DwarningAsError=true']
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


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _kill_group(pgid: int) -> bool:
    """Terminate a process group; returns True if anything was still running."""
    if not _group_alive(pgid):
        return False
    for sig, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return True
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline and _group_alive(pgid):
            time.sleep(0.05)
        if not _group_alive(pgid):
            break
    return True


def invoke(cmd: list[str], timeout: float, cwd: pathlib.Path | str, env: dict | None = None):
    """Run cmd in its own process group. Returns (rc, stdout, stderr, timed_out, leftover_killed).

    On timeout the whole group is killed (e.g. Apalache's JVM, CBMC). Processes the tool left
    running in its group after exiting are killed too. Daemons that start a new session escape.
    """
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
    except OSError as e:
        return None, b'', str(e).encode(), False, False
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err, False, _kill_group(proc.pid)
    except subprocess.TimeoutExpired:
        _kill_group(proc.pid)
        out, err = proc.communicate()
        return None, out or b'', err or b'', True, True


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
        results = []
        dec, i = json.JSONDecoder(), 0
        while True:
            rest = stdout[i:].lstrip()
            if not rest:
                break
            try:
                obj, n = dec.raw_decode(rest)
            except ValueError:
                break
            i = len(stdout) - len(rest) + n
            if isinstance(obj, dict) and isinstance(obj.get('verification-results'), dict):
                results.append(obj['verification-results'])
        errors = _matches((r'^error',), stderr.splitlines())
        if not results:
            if rc != 0 and _matches(VERUS_INPUT, lines):
                return done('input_error', errors)
            return done('clean' if rc == 0 else 'unrecognized', errors)
        obs['verus'] = {
            'crates': len(results),
            'verified': sum(r.get('verified', 0) for r in results),
            'errors': sum(r.get('errors', 0) for r in results),
            'success': all(r.get('success') for r in results),
            'encountered-error': any(r.get('encountered-error') for r in results),
        }
        if obs['verus']['errors'] > 0:
            return done('violation_reported', errors)
        if obs['verus']['encountered-error'] or rc != 0:
            return done('input_error', errors)
        return done('clean', [])

    # lean
    axioms: dict[str, list[str]] = {}
    for m in re.finditer(r"(?:^|: )'([^']+)' (?:does not depend on any axioms|depends on axioms: \[([^\]]*)\])", stdout + '\n' + stderr, re.M):
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


PROJECT_BACKENDS = ('kani', 'verus', 'lean')


def version_command(backend: str, project: bool) -> list[str]:
    if project and backend == 'kani':
        return ['cargo', 'kani', '--version']
    if project and backend == 'lean':
        return ['lake', '--version']
    return [backend, '--version']


def detect() -> dict:
    found = {}
    for tool in TOOLS:
        path = shutil.which(tool)
        entry = {'path': path, 'usable': False, 'version': None}
        if path:
            rc, out, err, timed, _ = invoke([path, '--version'], 30, '.')
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
    r.add_argument('file', type=pathlib.Path, nargs='?',
                   help='Input file. With --project: required for lean (a file inside the project), unused for kani/verus.')
    r.add_argument('--project', type=pathlib.Path, default=None,
                   help='Cargo crate (kani, verus) or Lake package (lean) root; the tool runs there.')
    r.add_argument('--property', help='Invariant (Quint run/verify), harness (Kani) or record label. '
                   'Not accepted for quint typecheck/test; use --quint-match.')
    r.add_argument('--bound', type=int, default=10)
    r.add_argument('--timeout', type=int, default=120)
    r.add_argument('--out', type=pathlib.Path, required=True)
    r.add_argument('--cwd', type=pathlib.Path, default=None,
                   help='Working directory for the tool (default: OUT/work, so build outputs stay inside OUT). '
                        'Not used with --project.')
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
    if args.samples < 1 or args.seed < 0 or args.bound < 0 or args.timeout < 1:
        ap.error('invalid bound, timeout, seed or samples')

    project = None
    input_path = None
    if args.project is not None:
        if args.backend not in PROJECT_BACKENDS:
            ap.error('--project is supported for kani, verus and lean only')
        if args.cwd is not None:
            ap.error('--cwd cannot be combined with --project')
        project = args.project.resolve()
        marker = 'lakefile.toml' if args.backend == 'lean' else 'Cargo.toml'
        if args.backend == 'lean' and (project / 'lakefile.lean').is_file():
            marker = 'lakefile.lean'
        if not (project / marker).is_file():
            ap.error(f'{project} has no {marker}')
        if args.backend == 'lean':
            if args.file is None:
                ap.error('lean --project needs the file to check (it should #print axioms the claimed theorem)')
            candidate = args.file if args.file.is_absolute() else project / args.file
            if not candidate.is_file():
                candidate = args.file.resolve()
            input_path = candidate.resolve()
            if not input_path.is_file() or not input_path.is_relative_to(project):
                ap.error('lean --project file must exist inside the project')
        elif args.file is not None:
            ap.error(f'{args.backend} --project takes no file argument; select the target with --property')
    else:
        if args.file is None or not args.file.is_file():
            ap.error('input file is missing or not a file')
        input_path = args.file.resolve()

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=False)
    env = None
    if project is not None:
        cwd = project
        if args.backend in ('kani', 'verus'):
            env = dict(os.environ, CARGO_TARGET_DIR=str(out_dir / 'work' / 'target'))
    elif args.cwd is None:
        cwd = out_dir / 'work'
        cwd.mkdir()
    else:
        cwd = args.cwd.resolve()

    if project is not None:
        files_before = tree_files(project)
        before = tree_digest(files_before)
    else:
        before = digest(input_path)
    tool_file = str(input_path.relative_to(project)) if project is not None and input_path else input_path
    cmd = command(args, tool_file, out_dir)
    start = time.monotonic()

    executable = shutil.which(cmd[0])
    version = None
    leftover = False
    if executable:
        cmd[0] = executable
        vcmd = version_command(args.backend, project is not None)
        vexe = shutil.which(vcmd[0])
        vc, vo, ve, vt, _ = invoke([vexe or vcmd[0], *vcmd[1:]], min(15, args.timeout), cwd, env)
        version = {
            'command': vcmd,
            'exit_code': vc,
            'stdout': vo.decode(errors='replace'),
            'stderr': ve.decode(errors='replace'),
            'timeout': vt,
        }
        rc, stdout, stderr, timed, leftover = invoke(cmd, args.timeout, cwd, env)
    else:
        rc, stdout, stderr, timed = None, b'', b'tool not found', False

    changed: dict = {}
    if project is not None:
        files_after = tree_files(project)
        modified = sorted(n for n in files_before if files_after.get(n) != files_before[n])
        created = sorted(set(files_after) - set(files_before))
        input_changed = bool(modified)
        changed = {'modified_or_deleted': modified, 'created': created}
    else:
        input_changed = (digest(input_path) if input_path.is_file() else None) != before

    (out_dir / 'stdout.log').write_bytes(stdout)
    (out_dir / 'stderr.log').write_bytes(stderr)

    if timed:
        observed = {'outcome': 'timeout', 'signals': [], 'warnings': []}
    elif rc is None:
        observed = {'outcome': 'tool_missing', 'signals': [stderr.decode(errors='replace')], 'warnings': []}
    else:
        observed = observe(args.backend, rc, stdout.decode(errors='replace'), stderr.decode(errors='replace'), args.property)
    if leftover and not timed:
        observed['warnings'].append('tool left processes running in its process group; they were killed')
    if changed.get('created'):
        observed['warnings'].append('files created in the project: ' + ', '.join(changed['created'][:10]))

    outcome = observed['outcome']
    status = {'timeout': 'TIMEOUT', 'tool_missing': 'TOOL_ERROR', 'input_error': 'TOOL_ERROR',
              'unrecognized': 'TOOL_ERROR'}.get(outcome, 'UNKNOWN')

    logs = {name: digest(out_dir / name) for name in ('stdout.log', 'stderr.log')}
    itf_path = out_dir / 'trace.itf.json'
    if itf_path.is_file():
        logs['trace.itf.json'] = digest(itf_path)

    is_quint = args.backend == 'quint'
    result = {
        'schema_version': 3,
        'backend': args.backend,
        'property': args.property,
        'input': str(input_path) if input_path else None,
        'input_sha256': digest(input_path) if input_path and project is not None else before,
        'project': None if project is None else {
            'path': str(project),
            'tree_sha256': before,
            'file_count': len(files_before),
            'changes': changed,
        },
        'git': git_info(project if project is not None else input_path),
        'input_changed': input_changed,
        'command': cmd,
        'cwd': str(cwd),
        'env': {'CARGO_TARGET_DIR': env['CARGO_TARGET_DIR']} if env else {},
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
    if input_changed:
        return 2
    return EXIT.get(outcome, 2)


if __name__ == '__main__':
    sys.exit(main())
