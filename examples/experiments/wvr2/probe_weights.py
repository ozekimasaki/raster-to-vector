#!/usr/bin/env python3
"""Measure per-face color response with black/white basis palettes."""
from __future__ import annotations
import argparse,json,os,shutil
from dataclasses import replace
from pathlib import Path
import numpy as np
from playwright.sync_api import sync_playwright
import verify_coverage as v

def main(out):
    rng=np.random.default_rng(314159); rows=[]; count=0
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':128,'height':128},device_scale_factor=1)
        for name in ['three_T','three_Y','three_alpha','circle_in_rect']:
            original,kind=v.cases()[name]
            for pi in [1,5]:
                profile=v.PROFILES[pi]
                _,ra,dom,areas=v.reference(original,kind,profile)
                target=np.stack([areas[i]*sh.opacity for i,sh in enumerate(original)],axis=-1)
                target=np.concatenate([target,(1-ra)[...,None]],axis=-1)
                for mode in ['normal','plus-lighter']:
                    cols=[]; alphas=[]
                    for i in range(len(original)):
                        shapes=[replace(sh,color=np.ones(3) if i==j else np.zeros(3)) for j,sh in enumerate(original)]
                        cp,a=v.decode(v.render_browser(page,v.svg_text(shapes,profile,mode),'inline'));count+=1
                        cols.append(cp[...,0]);alphas.append(a)
                    measured=np.stack(cols+[1-alphas[0]],axis=-1)
                    d=measured-target
                    # General bound does not assume measured coefficients sum to one.
                    bound=(abs(d).sum(axis=-1)+abs(d.sum(axis=-1)))/2
                    residual=0.; rendered_error=0.
                    for _ in range(3):
                        palette=rng.random((len(original),3))
                        shapes=[replace(sh,color=palette[i]) for i,sh in enumerate(original)]
                        cp,a=v.decode(v.render_browser(page,v.svg_text(shapes,profile,mode),'inline'));count+=1
                        predicted=np.einsum('hwi,ic->hwc',measured[...,:-1],palette)
                        residual=max(residual,float(abs(predicted-cp).max()))
                        exact=np.einsum('hwi,ic->hwc',target[...,:-1],palette)
                        rendered_error=max(rendered_error,float(abs(cp-exact).max()))
                    rows.append(dict(case=name,profile=pi,mode=mode,
                        max_palette_bound_from_measured_weights=float(bound.max()),
                        max_coefficient_error=float(abs(d).max()),
                        max_weight_sum_defect=float(abs(measured.sum(axis=-1)-1).max()),
                        max_alpha_variation_across_probes=float(np.max(np.ptp(np.stack(alphas),axis=0))),
                        max_random_palette_prediction_residual=residual,
                        max_random_palette_premult_error=rendered_error))
        version=browser.version;browser.close()
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(dict(seed=314159,render_count=count,chromium=version,scope='basis probes plus 3 random palettes; finite empirical residual, not a universal bound',runs=rows),indent=2)+'\n')
    print('render_count',count)
    for row in rows: print(row)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=Path('weight_probe_results.json'));main(parser.parse_args().out)
