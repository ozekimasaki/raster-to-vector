"""Explicit integration acceptance; writes only --out (except CFVX subprocess caches disabled).

Requires core, render, CFVX, and Shapely (original coverage harness import).
python tests/acceptance.py --out /path/to/results [--matrix]
"""
from __future__ import annotations
import argparse
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from PIL import Image, ImageDraw
import numpy as np
from r2v_lib.images import analyze, propose, compare, save_json, digest
from r2v_lib.render import render, render_worker


def cli(*args):
    run=subprocess.run([sys.executable,str(ROOT/'scripts/r2v.py'),*map(str,args)],capture_output=True,text=True,encoding='utf-8',timeout=240)
    if run.returncode: raise RuntimeError(run.stdout[-3000:]+run.stderr[-1000:])
    return json.loads(run.stdout)


def svg_file(path, body, size):
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">{body}</svg>',encoding='utf-8')


def synthesize(out):
    out.mkdir(parents=True,exist_ok=True)
    s=4; n=128
    im=Image.new('RGBA',(n*s,n*s)); d=ImageDraw.Draw(im)
    d.ellipse((16*s,16*s,112*s-1,112*s-1),fill='#197c91')
    d.ellipse((42*s,42*s,86*s-1,86*s-1),fill=(0,0,0,0))
    im.resize((n,n),Image.Resampling.BOX).save(out/'logo.png')
    svg_file(out/'logo.svg','<path fill="#197c91" fill-rule="evenodd" d="M112 64 A48 48 0 1 0 16 64 A48 48 0 1 0 112 64Z M86 64 A22 22 0 1 0 42 64 A22 22 0 1 0 86 64Z"/>',n)
    im=Image.new('RGBA',(n*s,n*s)); d=ImageDraw.Draw(im)
    d.line([(16*s,96*s),(48*s,32*s),(80*s,96*s),(112*s,32*s)],fill='#232338',width=4*s)
    im.resize((n,n),Image.Resampling.BOX).save(out/'line.png')
    svg_file(out/'line.svg','<path d="M16 96L48 32L80 96L112 32" fill="none" stroke="#232338" stroke-width="4" stroke-linejoin="bevel"/>',n)
    ill=Image.new('RGBA',(n,n),(0,0,0,0)); di=ImageDraw.Draw(ill)
    di.ellipse((24,36,104,120),fill='#3d7ea6')
    di.ellipse((40,12,88,68),fill='#f2d7b6')
    di.ellipse((50,30,62,42),fill='#2a2a2a')
    di.ellipse((66,30,78,42),fill='#2a2a2a')
    di.polygon([(52,50),(76,50),(64,62)],fill='#c45c5c')
    di.rectangle((46,74,82,102),fill='#e8c547')
    ill.save(out/'illustration.png')


def photo_candidate(labels, palette, path):
    """Validation-only grid region reconstruction, not a general/photo-quality engine.
    Build every pixel interface once, share it in reverse. Merge only collinear runs.
    No per-pixel rectangles, no independent curve simplification.
    """
    h,w=labels.shape; boundaries={}; shared_count=0
    def edge(label,a,b):
        if label>=0: boundaries.setdefault(int(label),[]).append((a,b))
    for y in range(h+1):
        for x in range(w):
            above=int(labels[y-1,x]) if y else -1
            below=int(labels[y,x]) if y<h else -1
            if above!=below:
                a=(x,y); b=(x+1,y); edge(below,a,b); edge(above,b,a); shared_count+=1
    for x in range(w+1):
        for y in range(h):
            left=int(labels[y,x-1]) if x else -1
            right=int(labels[y,x]) if x<w else -1
            if left!=right:
                a=(x,y); b=(x,y+1); edge(left,a,b); edge(right,b,a); shared_count+=1
    paths=[]
    directions={(1,0):0,(0,1):1,(-1,0):2,(0,-1):3}
    for label,edges in sorted(boundaries.items()):
        remaining=set(edges); outgoing={}
        for a,b in edges: outgoing.setdefault(a,set()).add(b)
        loops=[]
        while remaining:
            a,b=min(remaining); start=a; pts=[a]; steps=0
            while True:
                remaining.remove((a,b)); outgoing[a].remove(b); pts.append(b); steps+=1
                if b==start: break
                choices=outgoing.get(b,set())
                if not choices: raise RuntimeError('Open region boundary')
                direction=directions[(b[0]-a[0],b[1]-a[1])]
                # At diagonal contacts choose the right turn to retain four-connected faces.
                priority={1:0,0:1,3:2,2:3}
                c=min(choices,key=lambda c: priority[(directions[(c[0]-b[0],c[1]-b[1])]-direction)%4])
                a,b=b,c
                if steps>len(edges): raise RuntimeError('Invalid boundary cycle')
            corners=[]
            for i in range(len(pts)-1):
                prev=pts[i-1] if i else pts[-2]; point=pts[i]; nex=pts[i+1]
                if (point[0]-prev[0])*(nex[1]-point[1]) != (point[1]-prev[1])*(nex[0]-point[0]): corners.append(point)
            if corners: loops.append('M'+'L'.join(f'{x} {y}' for x,y in corners)+'Z')
        color='#'+''.join(f'{c:02x}' for c in palette[label])
        paths.append(f'<path id="color-{label}" fill="{color}" fill-rule="evenodd" d="{" ".join(loops)}"/>')
    svg_file(path,''.join(paths),w)
    return {'shared_grid_edges':shared_count,'method':'shared grid boundaries; no curve/gradient refinement',
            'limitations':['Stair-step boundaries','Posterized shading','No material alpha reconstruction'], 'status':'partial'}


def numerical(out):
    dest=out/'numerical'; dest.mkdir(parents=True,exist_ok=True)
    src=ROOT/'examples/experiments'
    shutil.copytree(src,dest/'sources',dirs_exist_ok=True)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
    results={}
    for name,command in {
        'cfvx':[sys.executable,str(dest/'sources/cfvx/review_checks.py')],
        'wvr2':[sys.executable,str(dest/'sources/wvr2/verify_math.py'),'--out',str(dest/'wvr2.json')],
    }.items():
        p=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',env=env,timeout=120)
        (dest/f'{name}.log').write_text(p.stdout+p.stderr,encoding='utf-8')
        results[name]={'exit_code':p.returncode}
        if p.returncode: raise RuntimeError(p.stderr)
    spec=importlib.util.spec_from_file_location('wvr1_checks',dest/'sources/wvr1/verify_wvr.py')
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    checks=m.analytic_checks(); save_json(dest/'wvr1.json',checks)
    results['wvr1']={'checks':len(checks)}
    save_json(dest/'summary.json',results); return results


def matrix(out):
    rows=[]; fixtures=ROOT/'examples/fixtures'
    for case,scale,phase,bg,route in itertools.product(['two_rects_plus-lighter','three_alpha_plus-lighter'],[.75,1,1.5],[0,.5],['transparent','white','black','color'],['inline','img']):
        name=f'{case}-{scale}-{phase}-{bg}-{route}'
        metadata=render_worker(fixtures/f'{case}.svg',out/name,'chromium',scale,(phase,phase),bg,route)
        image=np.asarray(Image.open(out/name/'render.png').convert('RGBA'))
        rows.append({'case':case,**metadata,'max_alpha':int(image[:,:,3].max()),'min_alpha':int(image[:,:,3].min())})
        if len(rows)%12==0: print(f'Matrix {len(rows)}/96',flush=True)
    # Compare actual img/inline routes at each profile, retaining finite-test residuals.
    differences=[]
    for case,scale,phase,bg in itertools.product(['two_rects_plus-lighter','three_alpha_plus-lighter'],[.75,1,1.5],[0,.5],['transparent','white','black','color']):
        a=np.asarray(Image.open(out/f'{case}-{scale}-{phase}-{bg}-inline/render.png')).astype(float)/255
        b=np.asarray(Image.open(out/f'{case}-{scale}-{phase}-{bg}-img/render.png')).astype(float)/255
        differences.append({'case':case,'scale':scale,'phase':phase,'background':bg,'route_max_difference':float(abs(a-b).max())})
    save_json(out/'matrix.json',{'renders':rows,'route_comparisons':differences,'claim':'Measured profiles only; no all-renderer or all-scale guarantee'})
    return {'count':len(rows),'route_max_difference':max(r['route_max_difference'] for r in differences)}


def main():
    p=argparse.ArgumentParser(); p.add_argument('--out',required=True,type=Path); p.add_argument('--matrix',action='store_true'); p.add_argument('--matrix-only',action='store_true'); p.add_argument('--reuse-illustration-draft',action='store_true'); args=p.parse_args()
    out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    if args.matrix_only: print(json.dumps(matrix(out/'matrix'))); return
    summary={'numerical':numerical(out),'cases':{}}
    synthesize(out/'synthetic')
    for name in ('logo','line'):
        source=out/f'synthetic/{name}.png'; svg=out/f'synthetic/{name}.svg'
        analyze(source,out/f'{name}/input')
        report=cli('check',source,'--svg',svg,'--renderer','chromium','--out',out/name/'check')
        # Independent second renderer for ordinary SVG.
        render(svg,out/name/'cairo','cairosvg')
        summary['cases'][name]=report['comparison']['metrics']
        print(name+' complete',flush=True)
    ill=out/'synthetic/illustration.png'
    analyze(ill,out/'illustration/input')
    draft=json.loads((out/'illustration/draft/draft-status.json').read_text(encoding='utf-8')) if args.reuse_illustration_draft else cli('cfvx-draft',ill,'--out',out/'illustration/draft')
    if not draft.get('candidate_exists'): raise RuntimeError('Illustration draft unavailable')
    report=cli('check',ill,'--svg',out/'illustration/draft/draft.svg','--renderer','chromium','--out',out/'illustration/check')
    summary['cases']['illustration']=report['comparison']['metrics']; print('illustration complete',flush=True)
    photo=ROOT/'examples/inputs/astronaut-256.png'
    analyze(photo,out/'photo/input'); candidates=[]
    for colors in (32,64,128):
        folder=out/f'photo/p{colors}'; meta=propose(photo,folder,colors)
        candidate=folder/'candidate.svg'
        notes=photo_candidate(np.load(folder/'labels.npy',allow_pickle=False),meta['palette_rgb'],candidate)
        report=cli('check',photo,'--svg',candidate,'--renderer','chromium','--out',folder/'check')
        row={'colors':colors,'metrics':report['comparison']['metrics'],'notes':notes}
        candidates.append(row); print(f'photo {colors} complete',flush=True)
    best=min(candidates,key=lambda r:r['metrics']['premultiplied_rgb_rmse'])
    summary['cases']['photo']={'candidates':candidates,'selected_colors':best['colors'],'status':'partial','reason':'Shading and boundary residuals remain; pipeline test, not photorealistic quality certificate'}
    if args.matrix: summary['matrix']=matrix(out/'matrix')
    save_json(out/'acceptance.json',summary); print(json.dumps(summary,indent=2))


if __name__=='__main__': main()
