#!/usr/bin/env python3
"""Compare cutout, plus-lighter, base fill, and crispEdges+AA on two rectangles.

Synthetic rectangles only. Encoded-sRGB box coverage. Not a general SVG repairer.
Run: python probe_crisp_aa.py --out DIR
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from r2v_lib.images import save_json  # noqa: E402
from r2v_lib.render import render  # noqa: E402
from r2v_lib.svg import inspect  # noqa: E402

COLORS = np.array([[196, 53, 77], [36, 105, 200]], float) / 255
LEFT = (40.5, 40.5, 64.5, 88.5)
RIGHT = (64.5, 40.5, 88.5, 88.5)
CASES = (
    'two_rects_normal',
    'two_rects_plus-lighter',
    'two_rects_base_fill',
    'two_rects_crisp_aa',
)
SCALES = (0.75, 1.0, 1.5)
PHASES = (0.0, 0.5)
BACKGROUNDS = ('transparent', 'white', 'black', 'color')
BG_RGB = {
    'transparent': None,
    'white': np.ones(3),
    'black': np.zeros(3),
    'color': np.array([75, 135, 197], float) / 255,
}


def cairosvg_available():
    if importlib.util.find_spec('cairosvg') is None:
        return False
    try:
        import cairosvg  # noqa: F401
        return True
    except Exception:
        return False


def box_cov(shape, w, h, scale=1, phase=0):
    x0, y0, x1, y1 = np.array(shape) * scale + phase
    y, x = np.mgrid[:h, :w]
    return (
        np.maximum(0, np.minimum(x + 1, x1) - np.maximum(x, x0))
        * np.maximum(0, np.minimum(y + 1, y1) - np.maximum(y, y0))
    )


def reference(w, h, scale, phase, background):
    a = box_cov(LEFT, w, h, scale, phase)
    b = box_cov(RIGHT, w, h, scale, phase)
    domain = np.clip(a + b, 0, 1)
    alpha = domain.copy()
    cp = a[:, :, None] * COLORS[0] + b[:, :, None] * COLORS[1]
    if background != 'transparent':
        cp = cp + (1 - alpha[:, :, None]) * BG_RGB[background]
        alpha = np.ones_like(alpha)
    interior = (a > 1e-8) & (b > 1e-8) & (np.abs(a + b - 1) < 1e-6)
    outer = (domain > 1e-8) & (domain < 1 - 1e-8) & ~interior
    return cp, alpha, interior, outer


def metrics(image, w, h, scale, phase, background):
    actual_a = image[:, :, 3]
    actual_c = image[:, :, :3] * actual_a[:, :, None]
    ref_c, ref_a, interior, outer = reference(w, h, scale, phase, background)
    da = actual_a - ref_a
    black = np.abs(actual_c - ref_c)
    white = np.abs(
        (actual_c + (1 - actual_a)[:, :, None]) - (ref_c + (1 - ref_a)[:, :, None])
    )
    err = np.maximum(black, white)

    def region(mask):
        if not mask.any():
            return {
                'pixels': 0,
                'alpha_deficit': None,
                'alpha_excess': None,
                'color_max': None,
            }
        return {
            'pixels': int(mask.sum()),
            'alpha_deficit': float(np.maximum(-da, 0)[mask].max()),
            'alpha_excess': float(np.maximum(da, 0)[mask].max()),
            'color_max': float(err[mask].max()),
        }

    return {
        'alpha_deficit_max': float(np.maximum(ref_a - actual_a, 0).max()),
        'alpha_excess_max': float(np.maximum(actual_a - ref_a, 0).max()),
        'color_black_white_max': float(err.max()),
        'interior': region(interior),
        'outer': region(outer),
    }


def peak(rows, key, nested=None):
    values = []
    for row in rows:
        item = row['metrics'][nested] if nested else row['metrics']
        val = item.get(key)
        if val is not None:
            values.append(val)
    return max(values) if values else None


def summarize(rows):
    summary = []
    for case in CASES:
        for renderer in ('chromium', 'cairosvg'):
            subset = [r for r in rows if r['case'] == case and r['renderer'] == renderer]
            if not subset:
                continue
            summary.append({
                'case': case,
                'renderer': renderer,
                'alpha_deficit_max': peak(subset, 'alpha_deficit_max'),
                'alpha_excess_max': peak(subset, 'alpha_excess_max'),
                'color_black_white_max': peak(subset, 'color_black_white_max'),
                'interior_alpha_deficit': peak(subset, 'alpha_deficit', 'interior'),
                'interior_color_max': peak(subset, 'color_max', 'interior'),
                'outer_alpha_excess': peak(subset, 'alpha_excess', 'outer'),
                'outer_color_max': peak(subset, 'color_max', 'outer'),
            })
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    fixtures = ROOT / 'examples' / 'fixtures'
    rows = []
    inspect_status = {}
    for case in CASES:
        svg = fixtures / f'{case}.svg'
        info, _root = inspect(svg)
        inspect_status[case] = info['status']
        if info['status'] != 'passed':
            raise RuntimeError(f'{case} failed inspect: {info.get("errors")}')
        for renderer in ('chromium', 'cairosvg'):
            if renderer == 'cairosvg' and (case == 'two_rects_plus-lighter' or not cairosvg_available()):
                continue
            profiles = [(1.0, 0.0, 'transparent')] if renderer == 'cairosvg' else [
                (scale, phase, bg)
                for scale in SCALES
                for phase in PHASES
                for bg in BACKGROUNDS
            ]
            for scale, phase, background in profiles:
                name = f'{case}-{renderer}-{scale}-{phase}-{background}'
                try:
                    meta = render(
                        svg, out / name, renderer, scale, (phase, phase),
                        background, 'inline',
                    )
                except RuntimeError as exc:
                    rows.append({
                        'case': case,
                        'renderer': renderer,
                        'scale': scale,
                        'phase': phase,
                        'background': background,
                        'status': 'failed',
                        'error': str(exc)[-500:],
                    })
                    print('fail', name, flush=True)
                    continue
                image = np.asarray(
                    Image.open(out / name / 'render.png').convert('RGBA')
                ).astype(float) / 255
                row = {
                    'case': case,
                    'renderer': renderer,
                    'scale': scale,
                    'phase': phase,
                    'background': background,
                    'status': meta['status'],
                    'metrics': metrics(
                        image, meta['width'], meta['height'], scale, phase, background,
                    ),
                }
                rows.append(row)
                print('ok', name, flush=True)
    result = {
        'scope': (
            'Two axis-aligned rectangles, encoded sRGB, analytical box coverage. '
            'Finite Chromium profiles plus one CairoSVG check. Not a renderer guarantee.'
        ),
        'inspect': inspect_status,
        'runs': rows,
        'summary': summarize(rows),
    }
    save_json(out / 'results.json', result)
    print(json.dumps({'inspect': inspect_status, 'summary': result['summary']}, indent=2))


if __name__ == '__main__':
    main()
