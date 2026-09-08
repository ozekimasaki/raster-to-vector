"""Analytical rectangle oracle and negative-render checks; explicit synthetic thresholds only."""
from pathlib import Path
import argparse
import importlib.util
import itertools
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import numpy as np
from PIL import Image
from r2v_lib.images import save_json
from r2v_lib.render import render

COLORS=np.array([[196,53,77],[36,105,200],[61,173,91]],float)/255


def box_cov(shape, w,h,scale=1,phase=0):
    x0,y0,x1,y1=np.array(shape)*scale+phase
    y,x=np.mgrid[:h,:w]
    return np.maximum(0,np.minimum(x+1,x1)-np.maximum(x,x0))*np.maximum(0,np.minimum(y+1,y1)-np.maximum(y,y0))


def matrix_oracle(folder):
    rows=[]
    for case,scale,phase,bg,route in itertools.product(['two_rects_plus-lighter','three_alpha_plus-lighter'],[.75,1,1.5],[0,.5],['transparent','white','black','color'],['inline','img']):
        png=folder/f'{case}-{scale}-{phase}-{bg}-{route}/render.png'
        im=np.asarray(Image.open(png).convert('RGBA')).astype(float)/255
        h,w=im.shape[:2]; alpha=np.zeros((h,w)); cp=np.zeros((h,w,3))
        parts=[((40.5,40.5,64.5,88.5),1,0),((64.5,40.5,88.5,88.5),1,1)] if case.startswith('two') else [((40.5,40.5,88.5,64.5),.25,0),((40.5,64.5,64.5,88.5),.65,1),((64.5,64.5,88.5,88.5),.9,2)]
        for rect,tau,color in parts:
            cov=box_cov(rect,w,h,scale,phase)*tau; alpha+=cov; cp+=cov[:,:,None]*COLORS[color]
        if bg!='transparent':
            background={'white':np.ones(3),'black':np.zeros(3),'color':np.array([75,135,197])/255}[bg]
            cp+=(1-alpha[:,:,None])*background; alpha[:]=1
        actual_a=im[:,:,3]; actual_c=im[:,:,:3]*actual_a[:,:,None]
        ae=float(abs(actual_a-alpha).max()); ce=float(abs(actual_c-cp).max())
        rows.append({'case':case,'scale':scale,'phase':phase,'background':bg,'route':route,
                     'alpha_max_error':ae,'premultiplied_color_max_error':ce,
                     'synthetic_threshold':4/255,'within_threshold':ae<=4/255 and ce<=4/255})
    result={'scope':'Rectangles, encoded sRGB, analytical box coverage, tested finite profiles only',
            'rows':rows,'within_threshold_count':sum(x['within_threshold'] for x in rows),'count':len(rows),
            'max_alpha_error':max(x['alpha_max_error'] for x in rows),'max_color_error':max(x['premultiplied_color_max_error'] for x in rows)}
    save_json(folder/'oracle.json',result); return {k:v for k,v in result.items() if k!='rows'}


def negative_tests(out):
    out.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('wvr1_negative',ROOT/'examples/experiments/wvr1/verify_wvr.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    rows=[]
    for case in ('base_fill','underlay_wrong','per_shape_opacity_overlap','intentional_gap'):
        svg=ROOT/f'examples/fixtures/{case}.svg'
        meta=render(svg,out/case,'chromium')
        metrics=module.metrics((out/case/'render.png').read_bytes(),case,1,(.5,.5))
        rows.append({'case':case,'render':meta,'metrics':metrics})
    by={x['case']:x['metrics'] for x in rows}
    assert by['underlay_wrong']['max_black_white_color_error']>.1
    assert by['underlay_wrong']['max_alpha_deficit']<.01
    assert by['per_shape_opacity_overlap']['max_alpha_excess']>.2
    assert by['base_fill']['max_black_white_color_error']<.02
    # Wrong ADD on true overlap, compared to analytic source-over cells.
    svg=ROOT/'examples/fixtures/overlap_raw_plus-lighter.svg'
    render(svg,out/'wrong-add','chromium')
    im=np.asarray(Image.open(out/'wrong-add/render.png').convert('RGBA')).astype(float)/255
    a=box_cov((42.5,46.5,75.5,80.5),128,128)
    b=box_cov((59.5,56.5,87.5,88.5),128,128)
    overlap=box_cov((59.5,56.5,75.5,80.5),128,128)
    reference_a=(a-overlap)*.45+(b-overlap)*.65+overlap*(.65+.45*(1-.65))
    error=float(np.maximum(im[:,:,3]-reference_a,0).max())
    assert error>.15
    result={'negative_cases':rows,'wrong_add_alpha_excess':error,'assertions':'passed',
            'meaning':'Tests successfully expose defective examples; these SVGs are not quality passes'}
    save_json(out/'negative-results.json',result); return {'negative_assertions':'passed','wrong_add_alpha_excess':error}


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--matrix',type=Path); p.add_argument('--out',required=True,type=Path); args=p.parse_args()
    if args.matrix: print(json.dumps(matrix_oracle(args.matrix),indent=2))
    print(json.dumps(negative_tests(args.out),indent=2))
