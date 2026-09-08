#!/usr/bin/env python3
"""Small, reproducible WVR counterexamples. Not a production SVG validator.

Dependencies: numpy, Pillow, cairosvg. Browser tests additionally need playwright
and Chromium. Run: python verify_wvr.py --out results
All comparisons use encoded-sRGB arithmetic intentionally. No network is used.
"""
from __future__ import annotations
import argparse
import importlib.metadata
import io
import json
import math
from pathlib import Path
import platform
import shutil
import sys
from typing import Callable

import numpy as np
from PIL import Image
import cairosvg

COLORS = {'A': '#c4354d', 'B': '#2469c8', 'C': '#f0b428', 'U': '#29bb61'}
VECTORS = {key: np.array([int(value[i:i+2], 16) for i in (1, 3, 5)]) / 255.
           for key, value in COLORS.items()}
CASES = (
    'cutout_shared', 'base_fill', 'underlay_wrong',
    'same_paint_cutout', 'same_paint_union',
    'uniform_group_opacity', 'per_shape_opacity_overlap',
    'geometry_gap', 'intentional_gap', 'triple_cutout', 'triple_layered', 'triple_reordered',
)
SCALES = (.75, 1., 1.5, 2.)
PHASES = ((0., 0.), (.25, .5), (.5, .5), (.75, .25))


def rect(x: float, y: float, w: float, h: float, color: str, opacity: float = 1.) -> str:
    return (f'<rect x="{x:.12g}" y="{y:.12g}" width="{w:.12g}" '
            f'height="{h:.12g}" fill="{COLORS[color]}" opacity="{opacity:.12g}"/>')


def make_svg(case: str, scale: float, phase: tuple[float, float]) -> str:
    n = round(64 * scale)
    left = rect(8, 8, 24, 48, 'A')
    right = rect(32, 8, 24, 48, 'B')
    base = rect(8, 8, 48, 48, 'A')
    body = {
        'cutout_shared': left + right,
        'base_fill': base + right,
        'underlay_wrong': rect(8, 8, 48, 48, 'U') + left + right,
        'same_paint_cutout': left + rect(32, 8, 24, 48, 'A'),
        'same_paint_union': base,
        'uniform_group_opacity': '<g opacity="0.5">' + base + right + '</g>',
        'per_shape_opacity_overlap': rect(8, 8, 48, 48, 'A', .5) + rect(32, 8, 24, 48, 'B', .5),
        'geometry_gap': rect(8, 8, 23.9, 48, 'A') + rect(32.1, 8, 23.9, 48, 'B'),
        'intentional_gap': rect(8, 8, 23.9, 48, 'A') + rect(32.1, 8, 23.9, 48, 'B'),
        'triple_cutout': rect(8, 8, 48, 24, 'A') + rect(8, 32, 24, 24, 'B') + rect(32, 32, 24, 24, 'C'),
        'triple_layered': base + rect(8, 32, 48, 24, 'B') + rect(32, 32, 24, 24, 'C'),
        'triple_reordered': rect(8, 8, 48, 48, 'B') + rect(32, 8, 24, 48, 'C') + rect(8, 8, 48, 24, 'A'),
    }[case]
    dx, dy = (v / scale for v in phase)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{n}" height="{n}" '
            f'viewBox="0 0 64 64" color-interpolation="sRGB">'
            f'<g transform="translate({dx:.14g},{dy:.14g})">{body}</g></svg>')


def coverage_rect(shape: tuple[float, float, float, float], n: int, scale: float,
                  phase: tuple[float, float]) -> np.ndarray:
    x0, y0, x1, y1 = shape
    xx, yy = np.meshgrid(np.arange(n), np.arange(n))
    x0, x1 = x0 * scale + phase[0], x1 * scale + phase[0]
    y0, y1 = y0 * scale + phase[1], y1 * scale + phase[1]
    wx = np.maximum(0., np.minimum(xx + 1., x1) - np.maximum(xx, x0))
    wy = np.maximum(0., np.minimum(yy + 1., y1) - np.maximum(yy, y0))
    return wx * wy


def reference(case: str, scale: float, phase: tuple[float, float]):
    n = round(64 * scale)
    if case.startswith('triple'):
        parts = [((8, 8, 56, 32), 'A'), ((8, 32, 32, 56), 'B'), ((32, 32, 56, 56), 'C')]
    elif case == 'intentional_gap':
        parts = [((8, 8, 31.9, 56), 'A'), ((32.1, 8, 56, 56), 'B')]
    else:
        other = 'A' if case.startswith('same_paint') else 'B'
        parts = [((8, 8, 32, 56), 'A'), ((32, 8, 56, 56), other)]
    alpha = np.zeros((n, n))
    premul = np.zeros((n, n, 3))
    for coords, color in parts:
        cov = coverage_rect(coords, n, scale, phase)
        alpha += cov
        premul += cov[..., None] * VECTORS[color]
    if case in ('uniform_group_opacity', 'per_shape_opacity_overlap'):
        alpha *= .5
        premul *= .5
    xx, yy = np.meshgrid(np.arange(n) + .5, np.arange(n) + .5)
    inside = ((xx > 16 * scale + phase[0]) & (xx < 48 * scale + phase[0]) &
              (yy > 16 * scale + phase[1]) & (yy < 48 * scale + phase[1]))
    near_x = np.abs(xx - (32 * scale + phase[0])) <= 2.
    near_y = np.abs(yy - (32 * scale + phase[1])) <= 2.
    roi = inside & (near_x | near_y if case.startswith('triple') else near_x)
    return premul, alpha, roi


def metrics(png: bytes, case: str, scale: float, phase: tuple[float, float]) -> dict:
    arr = np.asarray(Image.open(io.BytesIO(png)).convert('RGBA'), dtype=np.float64) / 255.
    actual_a = arr[..., 3]
    actual_c = arr[..., :3] * actual_a[..., None]
    ref_c, ref_a, roi = reference(case, scale, phase)
    if not roi.any():
        raise RuntimeError('Empty ROI')
    black_error = np.abs(actual_c - ref_c).max(axis=-1)
    white_error = np.abs(actual_c + 1 - actual_a[..., None] - (ref_c + 1 - ref_a[..., None])).max(axis=-1)
    return {
        'min_alpha': float(actual_a[roi].min()),
        'max_alpha_deficit': float(np.maximum(ref_a - actual_a, 0)[roi].max()),
        'max_alpha_excess': float(np.maximum(actual_a - ref_a, 0)[roi].max()),
        'max_black_white_color_error': float(np.maximum(black_error, white_error)[roi].max()),
        'roi_pixels': int(roi.sum()),
    }


def analytic_checks() -> list[dict]:
    checks = []
    def check(name: str, ok: bool, **values):
        if not bool(ok):
            raise AssertionError(name)
        checks.append({'name': name, 'passed': True, **values})
    a = .5; b = .5
    out_a = b + a * (1 - b)
    check('two_complementary_coverages', abs(out_a - .75) < 1e-12, alpha=out_a, leak=1-out_a)
    triple_leak = (1 - 1/3)**3
    check('three_equal_partition_coverages', abs(triple_leak - 8/27) < 1e-12, leak=triple_leak)
    micro_a = np.array([1., 0.]); micro_b = 1 - micro_a
    compose_first = np.mean(micro_b + micro_a * (1 - micro_b))
    filter_first = micro_b.mean() + micro_a.mean() * (1 - micro_b.mean())
    check('integration_order_matters', compose_first == 1 and filter_first == .75,
          compose_then_integrate=float(compose_first), integrate_then_compose=float(filter_first))
    ca, cb, cu = (VECTORS[k] for k in ('A', 'B', 'U'))
    ideal = a * ca + b * cb
    under = b * cb + (1-b) * (a*ca + (1-a)*cu)
    expected_delta = a*b*(cu-ca)
    check('wrong_underlay_tints_boundary', np.allclose(under - ideal, expected_delta),
          max_color_error=float(np.abs(under-ideal).max()))
    correct = b*cb + (1-b)*(a*ca + (1-a)*ca)
    check('back_paint_underlay_constant_two_face_case', np.allclose(correct, ideal))
    winner_back = b*cb + (1-b)*ca
    check('crisp_underlay_winner_back_matches_ideal', np.allclose(winner_back, ideal))
    winner_front = b*cb + (1-b)*a*ca + (1-b)*(1-a)*cb
    check('crisp_underlay_winner_front_bias', np.allclose(winner_front - ideal, a*b*(cb-ca)),
          max_color_error=float(np.abs(winner_front-ideal).max()))
    sil_cov = .5
    sil_after_opaque = sil_cov*1 + (1-sil_cov)*1
    check('crisp_silhouette_center_inside_kills_aa', sil_after_opaque == 1 and sil_cov == .5,
          result_alpha=sil_after_opaque, coverage=sil_cov)
    over1 = 1 - a*b
    over2 = a + (1-a)*over1
    over3 = b + (1-b)*over2
    check('crisp_ignored_double_over_not_partition', abs(over3-1) > .05, alpha=float(over3))
    transparent_overlap = .5 + .5*(1-.5)
    check('opacity_overlap_not_group_opacity', transparent_overlap == .75,
          per_shape_alpha=transparent_overlap, uniform_group_alpha=.5)
    p0 = np.array([-2., 1.]); p1 = np.array([4., 3.]); d = p1-p0
    chord = np.linalg.norm(d); normal = np.array([-d[1], d[0]])/chord
    mid = (p0+p1)/2; h = -3.7
    center = mid+h*normal; radius = math.hypot(chord/2, h)
    ep_error = max(abs(np.linalg.norm(p0-center)-radius), abs(np.linalg.norm(p1-center)-radius))
    check('endpoint_constrained_circle', ep_error < 1e-12, endpoint_residual=ep_error)
    q = .2
    hh = q/2-chord**2/(8*q)
    rr = math.hypot(chord/2, hh)
    check('sagitta_parameterization', abs(np.linalg.norm(mid+q*normal-(mid+hh*normal))-rr)<1e-12,
          q=q, h=float(hh), radius=float(rr))
    mat = np.array([[2., 1.], [.0, .5]])
    n = np.array([1., 1.])/math.sqrt(2)
    invtn = np.linalg.solve(mat.T, n)
    nd = invtn / np.linalg.norm(invtn)
    du = .3
    formula = du/np.linalg.norm(invtn)
    projected = float(nd@(mat@(du*n)))
    check('affine_normal_band_width', abs(projected-formula)<1e-12,
          user_half_width=du, device_half_width=float(formula), projection=projected)
    controls = np.array([[0., 0.], [1., 4.], [4., -2.], [5., 1.]])
    def bezier(c, t):
        return (1-t)**3*c[0]+3*(1-t)**2*t*c[1]+3*(1-t)*t*t*c[2]+t**3*c[3]
    err=max(np.linalg.norm(bezier(controls, t)-bezier(controls[::-1], 1-t)) for t in np.linspace(0,1,101))
    check('canonical_cubic_reverse', err < 1e-12, max_difference=float(err))
    ref = .5*ca + .25*cb + .25*VECTORS['C']
    layer = .25*VECTORS['C'] + .75*(.5*cb+.5*ca)
    check('triple_base_fill_alpha_healed_color_not', np.max(np.abs(layer-ref))>0.01,
          ideal_alpha=1., layered_alpha=1., max_color_error=float(np.max(np.abs(layer-ref))))
    reordered = .5*ca + .5*(.5*VECTORS['C']+.5*cb)
    check('orthogonal_partition_reordering', np.allclose(reordered, ref),
          max_color_error=float(np.max(np.abs(reordered-ref))))
    return checks


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return 'not installed'


def run(out: Path, skip_browser: bool) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    (out/'fixtures').mkdir(exist_ok=True)
    (out/'samples').mkdir(exist_ok=True)
    results = {'environment': {'python': sys.version.split()[0], 'platform': platform.platform(),
                               'numpy': package_version('numpy'), 'Pillow': package_version('Pillow'),
                               'cairosvg': package_version('cairosvg'), 'playwright': package_version('playwright')},
               'scope': {'cases': list(CASES), 'scales': list(SCALES), 'device_phases': list(PHASES),
                         'device_scale_factor': 1, 'reference': 'exact rectangle box coverage; encoded-sRGB arithmetic',
                         'roi': 'internal boundary bands, excludes outer silhouette',
                         'limits': 'synthetic rectangles only; no user SVG, curves, filters, full 2D phase grid, or Safari'},
               'analytic_checks': analytic_checks(), 'renders': [], 'skipped': []}
    def evaluate(engine: str, render: Callable[[str, int], bytes]):
        for case in CASES:
            for scale in SCALES:
                for phase in PHASES:
                    svg = make_svg(case, scale, phase)
                    png = render(svg, round(64*scale))
                    m = metrics(png, case, scale, phase)
                    results['renders'].append({'engine': engine, 'case': case, 'scale': scale,
                                               'phase': list(phase), **m})
                    if scale == 1 and phase == (.5,.5):
                        (out/'fixtures'/f'{case}.svg').write_text(svg, encoding='utf-8')
                        (out/'samples'/f'{engine}_{case}.png').write_bytes(png)
        print(f'{engine}: {len(CASES)*len(SCALES)*len(PHASES)} renders', flush=True)
    evaluate('cairosvg', lambda svg,n: cairosvg.svg2png(bytestring=svg.encode('utf-8')))
    if skip_browser:
        results['skipped'].append('chromium: explicitly skipped')
    else:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                path = shutil.which('chromium') or shutil.which('chromium-browser')
                options = {'headless': True, 'args': ['--no-sandbox', '--force-color-profile=srgb']}
                if path:
                    options['executable_path'] = path
                browser = p.chromium.launch(**options)
                results['environment']['chromium'] = browser.version
                context = browser.new_context(viewport={'width':128,'height':128}, device_scale_factor=1)
                page = context.new_page()
                page.route('**/*', lambda route: route.abort())
                def render_chromium(svg: str, n: int) -> bytes:
                    page.set_viewport_size({'width':n,'height':n})
                    page.set_content('<!doctype html><html><head><style>html,body{margin:0;padding:0;background:transparent}svg{display:block}</style></head><body>'+svg+'</body></html>')
                    return page.screenshot(omit_background=True, animations='disabled')
                evaluate('chromium', render_chromium)
                context.close(); browser.close()
        except (ImportError, RuntimeError) as exc:
            results['skipped'].append('chromium: '+repr(exc))
        except Exception as exc:
            results['skipped'].append('chromium failed: '+repr(exc))
    summary = []
    for engine in sorted({r['engine'] for r in results['renders']}):
        for case in CASES:
            rows = [r for r in results['renders'] if r['engine']==engine and r['case']==case]
            if rows:
                summary.append({'engine':engine, 'case':case, 'count':len(rows),
                                **{k:max(r[k] for r in rows) for k in ('max_alpha_deficit','max_alpha_excess','max_black_white_color_error')}})
    results['summary'] = summary
    (out/'results.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# WVR limited verification results','',
           'Rectangular synthetic scenes only. This is not a product-quality certificate.','',
           '| Engine | Case | N | Alpha deficit | Alpha excess | Black/white color error |',
           '|---|---|---:|---:|---:|---:|']
    for r in summary:
        lines.append('| {engine} | {case} | {count} | {max_alpha_deficit:.6f} | {max_alpha_excess:.6f} | {max_black_white_color_error:.6f} |'.format(**r))
    lines+=['','Analytic checks passed: '+str(len(results['analytic_checks'])),
            'Render count: '+str(len(results['renders'])), 'Skipped: '+repr(results['skipped'])]
    (out/'results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('\n'.join(lines),flush=True)
    return results


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('results'))
    parser.add_argument('--skip-browser', action='store_true')
    args=parser.parse_args()
    run(args.out, args.skip_browser)
