#!/usr/bin/env python3
"""Portable measurement CLI for the raster-to-vector skill."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    for name in ('analyze', 'propose-regions', 'cfvx-draft'):
        q = sub.add_parser(name); q.add_argument('input'); q.add_argument('--out', required=True)
        q.add_argument('--frame', type=int)
        if name == 'propose-regions': q.add_argument('--colors', type=int, required=True)
        if name == 'cfvx-draft':
            q.add_argument('--colors', type=int, default=22); q.add_argument('--tolerance', type=float, default=.65)
    q = sub.add_parser('mosaic-draft'); q.add_argument('input'); q.add_argument('--out', required=True)
    q.add_argument('--frame', type=int); q.add_argument('--colors', type=int, default=22)
    q.add_argument('--from-labels'); q.add_argument('--palette')
    q.add_argument('--mode', choices=('pixel', 'polygon', 'curve'), default='polygon')
    q.add_argument('--tolerance', type=float, default=.5); q.add_argument('--despeckle', type=int, default=0)
    q = sub.add_parser('inspect-svg'); q.add_argument('svg'); q.add_argument('--out', required=True)
    for name in ('render', '_render-worker'):
        q = sub.add_parser(name); q.add_argument('svg'); q.add_argument('--out', required=True)
        q.add_argument('--renderer', choices=('auto','chromium','cairosvg'), default='auto')
        q.add_argument('--scale', type=float, default=1.)
        q.add_argument('--phase', type=float, nargs=2, default=(0.,0.))
        q.add_argument('--background', choices=('transparent','white','black','color'), default='transparent')
        q.add_argument('--route', choices=('inline','img'), default='inline')
    q = sub.add_parser('compare'); q.add_argument('source'); q.add_argument('--rendered', required=True)
    q.add_argument('--out', required=True); q.add_argument('--frame', type=int)
    q = sub.add_parser('check'); q.add_argument('source'); q.add_argument('--svg', required=True)
    q.add_argument('--out', required=True); q.add_argument('--frame', type=int)
    q.add_argument('--renderer', choices=('auto','chromium','cairosvg'), default='auto')
    return p


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    args = build_parser().parse_args(argv)
    try:
        if args.command == 'doctor':
            # Minimal imports: doctor remains useful when image dependencies are absent.
            import importlib.util
            if any(importlib.util.find_spec(m) is None for m in ('numpy', 'PIL')):
                emit({'status': 'indeterminate', 'python': sys.version,
                      'modules': {m: importlib.util.find_spec(m) is not None for m in ('numpy','PIL','playwright','cairosvg','cv2','scipy','skimage')},
                      'renderers': {'chromium': {'available': None}, 'cairosvg': {'available': None}},
                      'note': 'Core dependencies missing; install requirements-core locally if environment permits'})
                return 0
            from r2v_lib.render import doctor
            emit(doctor()); return 0
        from r2v_lib.images import analyze, propose, compare, save_json, load_image, digest
        from r2v_lib.svg import inspect
        from r2v_lib.render import render, render_worker
        from r2v_lib.processes import run_bounded
        if args.command == 'analyze': result = analyze(args.input, args.out, args.frame)
        elif args.command == 'propose-regions': result = propose(args.input, args.out, args.colors, args.frame)
        elif args.command == 'inspect-svg':
            result, _ = inspect(args.svg); save_json(args.out, result)
            emit(result); return 0 if result['status'] == 'passed' else 2
        elif args.command in ('render', '_render-worker'):
            fn = render_worker if args.command == '_render-worker' else render
            result = fn(args.svg, args.out, args.renderer, args.scale, args.phase, args.background, args.route)
        elif args.command == 'compare': result = compare(args.source, args.rendered, args.out, args.frame)
        elif args.command == 'cfvx-draft':
            if not 2 <= args.colors <= 256 or not 0 < args.tolerance <= 10:
                raise ValueError('Invalid colors/tolerance')
            out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
            im, meta = load_image(args.input, args.frame); im.save(out/'draft-input.png')
            vendor = Path(__file__).resolve().parents[1] / 'vendor'
            import tempfile
            stage = Path(tempfile.mkdtemp(prefix='run-', dir=out))
            cmd = [sys.executable, '-m', 'cfvx', 'vectorize', str((out/'draft-input.png').resolve()),
                   '-o', str((stage/'draft.svg').resolve()), '--colors', str(args.colors), '--tolerance', str(args.tolerance)]
            try:
                import os
                env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
                run = run_bounded(cmd, cwd=vendor, env=env, timeout=180)
                (out/'cfvx-stdout.txt').write_text(run.stdout, encoding='utf-8')
                (out/'cfvx-stderr.txt').write_text(run.stderr, encoding='utf-8')
                for artifact in stage.glob('draft.*'):
                    shutil.copy2(artifact, out/artifact.name)
                result = {'status': 'draft_only', 'process_exit': run.returncode, 'source': meta,
                          'candidate_exists': (stage/'draft.svg').is_file(), 'run_directory': str(stage), 'quality_status': 'indeterminate',
                          'limitations': ['Alpha thresholding', 'Small region removal', 'Under-outline dilation',
                                          'No shared-boundary/WVR2 certificate', 'CFVX preview overall is not final SVG validation']}
            except subprocess.TimeoutExpired:
                result = {'status': 'indeterminate', 'candidate_exists': False, 'run_directory': str(stage),
                          'reason': 'CFVX exceeded 180 second budget; no complete candidate claimed; inspect this run directory'}
            save_json(out/'draft-status.json', result)
            emit(result)
            return 0 if result.get('candidate_exists') else 3
        elif args.command == 'mosaic-draft':
            from r2v_lib.mosaic import mosaic_draft
            result = mosaic_draft(
                args.input, args.out, args.colors, args.from_labels, args.mode, args.frame, args.tolerance,
                args.despeckle, args.palette,
            )
            emit(result)
            return 0 if result.get('candidate_exists') else 3
        elif args.command == 'check':
            out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
            info, root = inspect(args.svg)
            result = {'overall': 'indeterminate', 'svg': info, 'visual_review': 'indeterminate',
                      'topology': 'indeterminate', 'geometry_certificate': 'indeterminate',
                      'stopping_reason': 'measurement_complete_no_fidelity_threshold', 'revision_history': []}
            if root is None:
                result['overall'] = 'failed'; result['stopping_reason'] = 'SVG_rejected'
                save_json(out/'report.json', result); emit(result); return 2
            try:
                im, meta = load_image(args.source, args.frame); result['source'] = meta
                if abs(im.width-info['width']) > 1e-6 or abs(im.height-info['height']) > 1e-6:
                    raise ValueError('SVG canvas must match normalized source dimensions; no implicit resizing')
                result['render'] = render(args.svg, out/'render', args.renderer)
                result['comparison'] = compare(args.source, out/'render/render.png', out/'comparison', args.frame)
                shutil.copy2(out/'render/render.png', out/'preview.png')
                shutil.copy2(out/'comparison/comparison.png', out/'comparison.png')
            except Exception as exc:
                result['stopping_reason'] = 'validation_incomplete'; result['error'] = str(exc)
                save_json(out/'report.json', result); emit(result)
                return 2 if isinstance(exc, (ValueError, OSError)) else 3
            save_json(out/'report.json', result)
        else: raise ValueError('Unknown command')
        emit(result); return 0
    except (ValueError, OSError) as exc:
        emit({'status': 'failed', 'error': str(exc), 'error_type': type(exc).__name__}); return 2
    except Exception as exc:
        emit({'status': 'indeterminate', 'error': str(exc), 'error_type': type(exc).__name__}); return 3


if __name__ == '__main__':
    raise SystemExit(main())
