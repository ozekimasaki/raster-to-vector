#!/usr/bin/env python3
"""Compare circle serialization choices; this is not an SVG optimizer."""
from __future__ import annotations
import argparse, math, json, os, shutil
from pathlib import Path
import verify_coverage as v
from playwright.sync_api import sync_playwright

def make_circle(n,poly=False):
    def path(r):
        s=f'M{32+r:.15g} 32'
        for k in range(1,n+1):
            t=-2*math.pi*k/n
            x=32+r*math.cos(t);y=32+r*math.sin(t)
            if k==n:x,y=32+r,32
            s+=(f'L{x:.15g} {y:.15g}' if poly else f'A{r:.15g} {r:.15g} 0 0 0 {x:.15g} {y:.15g}')
        return s+'Z'
    return path

def main(out):
    out.mkdir(parents=True,exist_ok=True)
    (out/'fixtures').mkdir(exist_ok=True);(out/'samples').mkdir(exist_ok=True)
    rows=[]; original=v.circle_path
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':128,'height':128},device_scale_factor=1)
            for case in ['circle_in_rect','ring_and_disk']:
                sh,kind=v.cases()[case]
                for pi in [1,5]:
                    profile=v.PROFILES[pi];rcp,ra,dom,areas=v.reference(sh,kind,profile)
                    for n,poly in [(2,False),(4,False),(8,False),(16,False),(32,False),(64,False),(128,False),(128,True),(512,True)]:
                        v.circle_path=make_circle(n,poly)
                        svg=v.svg_text(sh,profile,'plus-lighter')
                        data=v.render_browser(page,svg,'inline');cp,a=v.decode(data)
                        row={'case':case,'profile':pi,'segments':n,'type':'polyline' if poly else 'arc',**v.metrics(cp,a,rcp,ra,dom,areas)}
                        rows.append(row)
                        if case=='ring_and_disk' and pi==1 and n==64 and not poly:
                            (out/'fixtures/ring_split_arcs64.svg').write_text(svg)
                            (out/'samples/ring_split_arcs64.png').write_bytes(data)
            browser.close()
    finally:
        v.circle_path=original
    (out/'arc_lowering.json').write_text(json.dumps(rows,indent=2)+'\n')
    print('render_count',len(rows))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=Path('coverage_results'));main(parser.parse_args().out)
