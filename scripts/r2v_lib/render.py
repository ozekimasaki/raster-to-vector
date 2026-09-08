from __future__ import annotations

import base64
import importlib.util
import json
import math
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .images import save_json
from .svg import NS, inspect
from .processes import run_bounded


def doctor():
    modules = {m: importlib.util.find_spec(m) is not None for m in ('numpy', 'PIL', 'playwright', 'cairosvg', 'scipy', 'cv2', 'skimage')}
    result = {'python': sys.version, 'modules': modules, 'renderers': {}}
    for name, source in {
        'cairosvg': "import cairosvg; print(cairosvg.__version__)",
        'chromium': "from playwright.sync_api import sync_playwright; import os; p=sync_playwright().start(); b=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or None, chromium_sandbox=True); print(b.version); b.close(); p.stop()"
    }.items():
        try:
            run = run_bounded([sys.executable, '-c', source], timeout=30)
            result['renderers'][name] = {'available': run.returncode == 0, 'version': run.stdout.strip() if run.returncode == 0 else None,
                                         'reason': run.stderr[-2000:] if run.returncode else None}
        except Exception as exc:
            result['renderers'][name] = {'available': False, 'reason': str(exc)}
    return result


def render_worker(svg, out, renderer, scale=1., phase=(0.,0.), background='transparent', route='inline'):
    info, root = inspect(svg)
    if root is None: raise ValueError('; '.join(info['errors']))
    if not math.isfinite(scale) or not 0 < scale <= 8: raise ValueError('Scale must be >0 and <=8')
    if any(not math.isfinite(x) or abs(x) > 8 for x in phase): raise ValueError('Phase must be finite and within 8 device pixels')
    w, h = math.ceil(info['width']*scale), math.ceil(info['height']*scale)
    if w*h > 25_000_000 or max(w,h) > 8192: raise ValueError('Output exceeds rendering limits')
    colors = {'transparent': None, 'white': '#ffffff', 'black': '#000000', 'color': '#4b87c5'}
    if background not in colors: raise ValueError('Unknown background')
    if renderer == 'cairosvg' and route != 'inline': raise ValueError('img route requires Chromium')
    if renderer == 'cairosvg' and info['plus_lighter']:
        raise RuntimeError('plus-lighter cannot be verified by the CairoSVG route; use Chromium')
    outer = ET.Element(f'{{{NS}}}svg', {'width': str(w), 'height': str(h), 'viewBox': f'0 0 {w} {h}'})
    if colors[background]:
        ET.SubElement(outer, f'{{{NS}}}rect', {'width': str(w), 'height': str(h), 'fill': colors[background]})
    group = ET.SubElement(outer, f'{{{NS}}}g', {'transform': f'translate({phase[0]} {phase[1]}) scale({scale})'})
    root.set('width', str(info['width'])); root.set('height', str(info['height']))
    group.append(root)
    safe = ET.tostring(outer, encoding='utf-8')
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    if renderer == 'chromium':
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or None, chromium_sandbox=True)
            version = browser.version
            try:
                context = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1, service_workers='block')
                context.route('**/*', lambda r: r.abort())
                page = context.new_page(); page.set_default_timeout(15000)
                csp = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'none'; font-src 'none'; connect-src 'none'"
                content = safe.decode() if route == 'inline' else '<img src="data:image/svg+xml;base64,' + base64.b64encode(safe).decode() + '">'
                page.set_content(f'<html><head><meta http-equiv="Content-Security-Policy" content="{csp}"><style>html,body{{margin:0;padding:0;background:transparent}}svg,img{{display:block}}</style></head><body>{content}</body></html>')
                if route == 'img':
                    page.locator('img').evaluate('(el) => el.decode()')
                page.screenshot(path=str(out/'render.png'), omit_background=True, animations='disabled')
            finally: browser.close()
    elif renderer == 'cairosvg':
        import cairosvg
        from cairosvg.surface import PNGSurface
        def deny(*args, **kwargs): raise ValueError('Resource loading denied')
        PNGSurface.convert(bytestring=safe, write_to=str(out/'render.png'), output_width=w, output_height=h,
                           unsafe=False, url_fetcher=deny)
        version = cairosvg.__version__
    else: raise ValueError('Unknown renderer')
    meta = {'status': 'passed', 'renderer': renderer, 'version': version, 'svg_sha256': info['svg_sha256'],
            'scale': scale, 'phase_device_px': list(phase), 'background': background, 'route': route,
            'width': w, 'height': h, 'device_scale_factor': 1, 'color_space': 'encoded_sRGB',
            'geometry_certificate': 'indeterminate', 'quality_status': 'indeterminate'}
    save_json(out/'render.json', meta)
    return meta


def render(svg, out, renderer='auto', scale=1., phase=(0.,0.), background='transparent', route='inline'):
    info, root = inspect(svg)
    if root is None: raise ValueError('; '.join(info['errors']))
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    names = ['chromium', 'cairosvg'] if renderer == 'auto' else [renderer]
    attempts = []
    cli = Path(__file__).resolve().parents[1] / 'r2v.py'
    for name in names:
        command = [sys.executable, str(cli), '_render-worker', str(Path(svg).resolve()), '--out', str(out.resolve()),
                   '--renderer', name, '--scale', str(scale), '--phase', *map(str,phase), '--background', background, '--route', route]
        try:
            run = run_bounded(command, timeout=45)
            if run.returncode == 0:
                meta = json.loads(run.stdout); meta['failed_attempts'] = attempts
                save_json(out/'render.json', meta); return meta
            attempts.append({'renderer': name, 'error': run.stdout[-2000:] or run.stderr[-2000:]})
        except subprocess.TimeoutExpired:
            attempts.append({'renderer': name, 'error': '45 second worker timeout'})
    meta = {'status': 'indeterminate', 'attempts': attempts, 'svg_sha256': info['svg_sha256']}
    save_json(out/'render.json', meta)
    raise RuntimeError(json.dumps(meta, ensure_ascii=False))
