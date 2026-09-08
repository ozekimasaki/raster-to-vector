#!/usr/bin/env python3
"""Synthetic coverage-compositing experiments; not a general SVG repair engine."""
from __future__ import annotations
import argparse, base64, io, json, math, platform, sys, os, shutil
from dataclasses import dataclass
from pathlib import Path
from importlib.metadata import version
import numpy as np
import shapely
from shapely.geometry import Polygon, box
from shapely.affinity import affine_transform
from PIL import Image
import cairosvg
from playwright.sync_api import sync_playwright

W = 128
COLORS = [np.array([196,53,77])/255, np.array([36,105,200])/255, np.array([61,173,91])/255]
PROFILES = [
    (0.75,0.0,0.13,0.37), (1.0,0.0,0.5,0.5), (1.5,0.0,0.5,0.5),
    (1.0,17.0,0.13,0.37), (0.75,17.0,0.5,0.5), (1.5,17.0,0.13,0.37)]
Y,X=np.mgrid[0:W,0:W]
PIXELS=shapely.box(X,Y,X+1,Y+1)

@dataclass
class Shape:
    geom: object
    color: np.ndarray
    opacity: float=1.0
    gradient_end: np.ndarray|None=None
    special: str|None=None


def path_data(g):
    if g.is_empty: return ''
    polygons=[g] if g.geom_type=='Polygon' else list(g.geoms)
    parts=[]
    for p in polygons:
        for ring in [p.exterior,*p.interiors]:
            coords=list(ring.coords)
            parts.append('M'+'L'.join(f'{x:.15g} {y:.15g}' for x,y in coords)+'Z')
    return ' '.join(parts)


def circle_path(r):
    return f'M{32+r} 32 A{r} {r} 0 1 0 {32-r} 32 A{r} {r} 0 1 0 {32+r} 32 Z'


def cases():
    D=box(8,8,56,56)
    A=box(8,8,56,32); B=box(8,32,32,56); C=box(32,32,56,56)
    make=lambda g,c,a=1: Shape(g,COLORS[c],a)
    left=box(8,8,32,56); right=box(32,8,56,56)
    tri=Polygon([(8,8),(56,8),(56,56)])
    j=(31.3,32.7)
    yy=[Polygon([j,(32,8),(8,8),(8,56)]),Polygon([j,(8,56),(56,56)]),Polygon([j,(56,56),(56,8),(32,8)])]
    oa=box(10,14,43,48); ob=box(27,24,55,56)
    ta,tb=.45,.65; ab=tb+ta*(1-tb)
    mixed=(tb*COLORS[1]+ta*(1-tb)*COLORS[0])/ab
    return {
      'two_rects':([make(left,0),make(right,1)],'partition'),
      'three_T':([make(A,0),make(B,1),make(C,2)],'partition'),
      'three_alpha':([make(A,0,.25),make(B,1,.65),make(C,2,.9)],'partition'),
      'two_diagonal':([make(tri,0),make(D.difference(tri),1)],'partition'),
      'three_Y':([make(g,i) for i,g in enumerate(yy)],'partition'),
      'circle_in_rect':([Shape(D,COLORS[0],special='rect_minus_circle'),Shape(None,COLORS[1],special='disk17')],'partition'),
      'ring_and_disk':([Shape(None,COLORS[0],special='ring'),Shape(None,COLORS[1],special='disk14')],'partition'),
      'intentional_slit':([make(box(8,8,31.85,56),0),make(box(32.15,8,56,56),1)],'partition'),
      'overlap_raw':([make(oa,0,ta),make(ob,1,tb)],'true_overlap'),
      'overlap_partitioned':([make(oa.difference(ob),0,ta),Shape(oa.intersection(ob),mixed,ab),make(ob.difference(oa),1,tb)],'partition'),
      'diagonal_gradient':([Shape(tri,COLORS[0],gradient_end=np.array([.9,.8,.1])),Shape(D.difference(tri),COLORS[1],gradient_end=np.array([.1,.8,.9]))],'partition')
    }


def transform(profile):
    scale,deg,px,py=profile
    t=math.radians(deg); a=scale*math.cos(t); b=-scale*math.sin(t)
    c=scale*math.sin(t); d=scale*math.cos(t)
    tx=64+px-32*a-32*b; ty=64+py-32*c-32*d
    return a,b,c,d,tx,ty


def circle_coverage(cx,cy,r):
    dx0=X-cx; dx1=X+1-cx; dy0=Y-cy; dy1=Y+1-cy
    maxd=np.maximum(dx0*dx0,dx1*dx1)+np.maximum(dy0*dy0,dy1*dy1)
    minx=np.maximum(np.maximum(dx0,-dx1),0)
    miny=np.maximum(np.maximum(dy0,-dy1),0)
    mind=minx*minx+miny*miny
    result=(maxd<=r*r).astype(float)
    by,bx=np.where((mind<r*r)&(maxd>r*r))
    def primitive(u):
        u=min(r,max(-r,u))
        return .5*(u*math.sqrt(max(0,r*r-u*u))+r*r*math.asin(u/r))
    for yy,xx in zip(by,bx):
        lo=max(float(xx),cx-r); hi=min(float(xx+1),cx+r)
        cuts=[lo,hi]
        for yb in [float(yy),float(yy+1)]:
            v=yb-cy
            if abs(v)<r:
                q=math.sqrt(r*r-v*v)
                for xc in [cx-q,cx+q]:
                    if lo<xc<hi:cuts.append(xc)
        cuts=sorted(set(cuts)); area=0.
        for l,u in zip(cuts[:-1],cuts[1:]):
            mid=(l+u)/2; root=math.sqrt(max(0,r*r-(mid-cx)**2))
            top=min(yy+1,cy+root); bottom=max(yy,cy-root)
            if top<=bottom:continue
            tc,ts=(cy,1) if cy+root<yy+1 else (float(yy+1),0)
            bc,bs=(cy,-1) if cy-root>yy else (float(yy),0)
            area+=(tc-bc)*(u-l)+(ts-bs)*(primitive(u-cx)-primitive(l-cx))
        result[yy,xx]=min(1,max(0,area))
    return result


def shape_integrals(shape,profile):
    a,b,c,d,tx,ty=transform(profile)
    if shape.special:
        r17=circle_coverage(64+profile[2],64+profile[3],17.25*profile[0])
        if shape.special=='disk17':return r17,None
        if shape.special=='rect_minus_circle':
            g=affine_transform(box(8,8,56,56),[a,b,c,d,tx,ty])
            total=shapely.area(shapely.intersection(PIXELS,g))
            return np.clip(total-r17,0,1),None
        r14=circle_coverage(64+profile[2],64+profile[3],14*profile[0])
        if shape.special=='disk14':return r14,None
        return np.clip(circle_coverage(64+profile[2],64+profile[3],23*profile[0])-r14,0,1),None
    g=affine_transform(shape.geom,[a,b,c,d,tx,ty])
    clip=shapely.intersection(PIXELS,g)
    area=shapely.area(clip)
    if shape.gradient_end is None:return area,None
    centroid=shapely.centroid(clip)
    valid=~shapely.is_empty(centroid)
    xc=np.zeros_like(area); yc=np.zeros_like(area)
    xc[valid]=shapely.get_x(centroid[valid]); yc[valid]=shapely.get_y(centroid[valid])
    det=a*d-b*c
    userx=(d*(xc-tx)-b*(yc-ty))/det
    moment=area*(userx-8)/48
    return area,moment


def reference(shapes,kind,profile):
    areas=[]; cp=np.zeros((W,W,3)); alpha=np.zeros((W,W))
    for sh in shapes:
        area,moment=shape_integrals(sh,profile); areas.append(area)
        alpha+=sh.opacity*area
        cp+=sh.opacity*area[...,None]*sh.color
        if moment is not None:cp+=sh.opacity*moment[...,None]*(sh.gradient_end-sh.color)
    if kind=='true_overlap':
        overlap=Shape(shapes[0].geom.intersection(shapes[1].geom),COLORS[0])
        ov,_=shape_integrals(overlap,profile)
        loss=shapes[0].opacity*shapes[1].opacity*ov
        alpha-=loss
        cp-=loss[...,None]*shapes[0].color
    domain=np.sum(areas,axis=0)
    if kind=='true_overlap': domain-=ov
    domain=np.clip(domain,0,1)
    return cp,alpha,domain,np.stack(areas)


def svg_text(shapes,profile,mode,isolated=True,background=None):
    defs=[]; paths=[]
    for i,sh in enumerate(shapes):
        if sh.special=='rect_minus_circle':d=path_data(box(8,8,56,56))+' '+circle_path(17.25)
        elif sh.special=='disk17':d=circle_path(17.25)
        elif sh.special=='ring':d=circle_path(23)+' '+circle_path(14)
        elif sh.special=='disk14':d=circle_path(14)
        else:d=path_data(sh.geom)
        color=lambda v:'rgb('+','.join(f'{float(x)*100:.12g}%' for x in v)+')'
        fill=color(sh.color)
        if sh.gradient_end is not None:
            gid=f'g{i}'
            defs.append(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="8" y1="0" x2="56" y2="0" color-interpolation="sRGB"><stop offset="0" stop-color="{color(sh.color)}"/><stop offset="1" stop-color="{color(sh.gradient_end)}"/></linearGradient>')
            fill=f'url(#{gid})'
        paths.append(f'<path d="{d}" fill="{fill}" fill-rule="evenodd" opacity="{sh.opacity:.15g}" style="mix-blend-mode:{mode}"/>')
    a,b,c,d,tx,ty=transform(profile)
    under=''
    if background is not None:
        under=f'<rect width="128" height="128" fill="{color(background)}"/>'
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">'
            +'<defs>'+''.join(defs)+'</defs>'+under+
            f'<g style="isolation:{"isolate" if isolated else "auto"}"><g transform="matrix({a:.15g} {c:.15g} {b:.15g} {d:.15g} {tx:.15g} {ty:.15g})">'+''.join(paths)+'</g></g></svg>')


def decode(data):
    arr=np.asarray(Image.open(io.BytesIO(data)).convert('RGBA'),dtype=float)/255
    return arr[:,:,:3]*arr[:,:,3,None],arr[:,:,3]


def metrics(cp,alpha,ref_cp,ref_alpha,domain,areas):
    deficit=np.maximum(ref_alpha-alpha,0); excess=np.maximum(alpha-ref_alpha,0)
    black=np.abs(cp-ref_cp)
    white=np.abs((cp+(1-alpha)[...,None])-(ref_cp+(1-ref_alpha)[...,None]))
    err=np.maximum(black,white)
    interior=(domain>1-1e-8)&((areas>1e-8).sum(axis=0)>=2)
    outer=(domain>1e-8)&(domain<1-1e-8)
    return {'alpha_deficit_max':float(deficit.max()),'alpha_excess_max':float(excess.max()),
      'color_black_white_max':float(err.max()),
      'color_interior_max':float(err[interior].max()) if interior.any() else None,
      'color_outer_max':float(err[outer].max()) if outer.any() else None,
      'premult_rgb_mae':float(black.mean()),'interior_pixel_count':int(interior.sum())}


def render_browser(page,svg,route):
    if route=='inline':body=svg
    else:body='<img width="128" height="128" src="data:image/svg+xml;base64,'+base64.b64encode(svg.encode()).decode()+'">'
    page.set_content('<style>html,body{margin:0;background:transparent}svg,img{display:block}</style>'+body)
    if route=='img':page.eval_on_selector('img','el=>el.decode()')
    return page.screenshot(omit_background=True,animations='disabled')


def run(out):
    out.mkdir(parents=True,exist_ok=True); (out/'fixtures').mkdir(exist_ok=True);(out/'samples').mkdir(exist_ok=True)
    result={'environment':{'python':sys.version.split()[0], 'numpy':np.__version__,'shapely':shapely.__version__,'cairosvg':cairosvg.__version__,'playwright':version('playwright')},'profiles':PROFILES,'runs':[],'background_runs':[], 'scope':'synthetic scenes only; color arithmetic is encoded sRGB; not a generic SVG repair engine'}
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
        result['environment']['chromium']=browser.version
        page=browser.new_page(viewport={'width':W,'height':W},device_scale_factor=1)
        result['css_supports_plus_lighter']=page.evaluate("CSS.supports('mix-blend-mode','plus-lighter')")
        for name,(shapes,kind) in cases().items():
            for pi,profile in enumerate(PROFILES):
                rcp,ra,domain,areas=reference(shapes,kind,profile)
                for mode in ['normal','plus-lighter']:
                    svg=svg_text(shapes,profile,mode)
                    if pi==1:(out/'fixtures'/f'{name}_{mode}.svg').write_text(svg)
                    for engine in ['chromium_inline','chromium_img','cairosvg']:
                        data=cairosvg.svg2png(bytestring=svg.encode()) if engine=='cairosvg' else render_browser(page,svg,engine.split('_')[1])
                        cp,alpha=decode(data)
                        result['runs'].append({'case':name,'kind':kind,'mode':mode,'engine':engine,'profile':pi,**metrics(cp,alpha,rcp,ra,domain,areas)})
                        if pi==1 and engine=='chromium_inline':(out/'samples'/f'{name}_{mode}.png').write_bytes(data)
            (out/'checkpoint.json').write_text(json.dumps(result))
            print('done',name,flush=True)
        sh,kind=cases()['three_alpha']; profile=PROFILES[1]
        rcp,ra,domain,areas=reference(sh,kind,profile)
        for isolate in [True,False]:
            for bg in [np.zeros(3),np.ones(3),np.array([.8,.1,.7])]:
                svg=svg_text(sh,profile,'plus-lighter',isolated=isolate,background=bg)
                data=render_browser(page,svg,'inline');cp,alpha=decode(data)
                target=rcp+(1-ra)[...,None]*bg
                result['background_runs'].append({'isolation':isolate,'background':bg.tolist(),'max_color_error':float(np.abs(cp-target).max()),'alpha_deficit':float((1-alpha).max())})
        browser.close()
    result['render_count']=len(result['runs'])+len(result['background_runs'])
    summary=[]
    for name in cases():
        for engine in ['chromium_inline','chromium_img','cairosvg']:
            for mode in ['normal','plus-lighter']:
                rows=[r for r in result['runs'] if r['case']==name and r['engine']==engine and r['mode']==mode]
                keys=['alpha_deficit_max','alpha_excess_max','color_black_white_max','color_interior_max','color_outer_max']
                summary.append({'case':name,'engine':engine,'mode':mode,**{k:max((r[k] for r in rows if r[k] is not None),default=None) for k in keys}})
    result['summary']=summary
    (out/'results.json').write_text(json.dumps(result,indent=2))
    md=['# Synthetic coverage experiment results','','All values are 0..1; maxima over six profiles.','', '| Case | Engine | Mode | Alpha deficit | Alpha excess | Color max | Interior color | Outer color |','|---|---|---|---:|---:|---:|---:|---:|']
    for r in summary:
        vals=[r[k] for k in ['alpha_deficit_max','alpha_excess_max','color_black_white_max','color_interior_max','color_outer_max']]
        md.append('|'+ '|'.join([r['case'],r['engine'],r['mode']]+['n/a' if x is None else f'{x:.8f}' for x in vals])+'|')
    (out/'results.md').write_text('\n'.join(md)+'\n')
    print('render_count',result['render_count'])

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=Path('coverage_results'))
    run(parser.parse_args().out)
