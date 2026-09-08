#!/usr/bin/env python3
"""Deterministic numerical checks of the proposed equations, not a proof engine."""
from __future__ import annotations
import argparse, itertools, json, math
from pathlib import Path
import numpy as np
from scipy.integrate import quad

RNG = np.random.default_rng(20260908)

def main(out: Path):
    checks = []
    def record(name, error, count, tol=1e-10):
        error = float(error)
        assert np.isfinite(error) and error <= tol, (name, error, tol)
        checks.append(dict(name=name, cases=count, max_absolute_error=error, tolerance=tol, passed=True))
    # Disjoint samples: composite at each sample, then average, vs additive averages.
    worst=0.
    for _ in range(100):
        n,m=6,317
        labels=RNG.integers(0,n+1,m)
        tau=RNG.random((n,m)); col=RNG.random((n,m,3))
        cp=np.zeros((m,3)); alpha=np.zeros(m)
        ac=np.zeros(3); aa=0.
        for i in range(n):
            a=tau[i]*(labels==i)
            c=col[i]*a[:,None]
            cp=c+(1-a[:,None])*cp; alpha=a+(1-a)*alpha
            ac+=c.mean(axis=0); aa+=a.mean()
        worst=max(worst,np.max(np.abs(cp.mean(axis=0)-ac)),abs(alpha.mean()-aa))
    record('disjoint_additive_equals_samplewise_compositing',worst,100)
    # Overlap partition: effective cell premult values equal pointwise layer composite.
    worst=0.
    for _ in range(100):
        n=5; tau=RNG.random(n); col=RNG.random((n,3)); masks=RNG.integers(0,2,(n,211))
        a=np.zeros(211); c=np.zeros((211,3))
        for i in range(n):
            ai=tau[i]*masks[i]; c=ai[:,None]*col[i]+(1-ai[:,None])*c; a=ai+(1-ai)*a
        for membership in itertools.product([0,1],repeat=n):
            active=np.array(membership); hit=(masks.T==active).all(axis=1)
            aj=tau*active
            alpha=1-np.prod(1-aj)
            color=sum((aj[i]*col[i]*np.prod(1-aj[i+1:]) for i in range(n)),np.zeros(3))
            if hit.any(): worst=max(worst,abs(a[hit][0]-alpha),np.max(np.abs(c[hit][0]-color)))
    record('overlap_cell_formula_matches_source_over',worst,100)
    # Circle Green-integral primitive compared with numerical quadrature.
    worst=0.
    for _ in range(300):
        cx,cy=RNG.uniform(-10,10,2); r=RNG.uniform(.01,10); t0=RNG.uniform(-5,5); t1=t0+RNG.uniform(-6,6)
        val=.5*(r*cx*(math.sin(t1)-math.sin(t0))+r*cy*(math.cos(t0)-math.cos(t1))+r*r*(t1-t0))
        numeric=quad(lambda t:.5*(r*cx*math.cos(t)+r*cy*math.sin(t)+r*r),t0,t1,epsabs=1e-11)[0]
        reverse=.5*(r*cx*(math.sin(t0)-math.sin(t1))+r*cy*(math.cos(t1)-math.cos(t0))+r*r*(t0-t1))
        worst=max(worst,abs(val-numeric),abs(val+reverse))
    record('circle_edge_area_integral_and_reversal',worst,300)
    # Triangle pixel partition: shared diagonal cancels; moments integrate an affine paint.
    def moments(poly):
        area=mx=my=0.
        for (x,y),(u,v) in zip(poly,poly[1:]+poly[:1]):
            z=x*v-y*u; area+=z/2; mx+=(x+u)*z/6; my+=(y+v)*z/6
        return np.array([area,mx,my])
    tri1=[(0.,0.),(1.,0.),(1.,1.)]; tri2=[(0.,0.),(1.,1.),(0.,1.)]
    reference=np.array([1.,.5,.5]); got=moments(tri1)+moments(tri2)
    record('shared_edges_conserve_area_and_first_moments',np.max(abs(got-reference)),1)
    worst=0.
    for _ in range(100):
        u,v,w=RNG.random(3)
        for tri in [tri1,tri2]:
            am=moments(tri); center=np.mean(tri,axis=0)
            direct=am[0]*(u+v*center[0]+w*center[1])
            worst=max(worst,abs(am@np.array([u,v,w])-direct))
    record('affine_paint_integral_from_moments',worst,200)
    # General palette bound, including nonzero sums.
    worst=0.
    for _ in range(200):
        d=RNG.normal(size=6)
        exact=max(abs(np.dot(d,c)) for c in itertools.product([0.,1.],repeat=6))
        bound=(abs(d).sum()+abs(d.sum()))/2
        worst=max(worst,abs(exact-bound))
    record('palette_error_bound_equals_exhaustive_vertices',worst,200)
    # Partition delta including background sums to zero.
    worst=0.
    for _ in range(200):
        w=RNG.dirichlet(np.ones(5)); v=RNG.dirichlet(np.ones(5)); d=w-v
        exact=max(abs(np.dot(d,c)) for c in itertools.product([0.,1.],repeat=5))
        worst=max(worst,abs(exact-abs(d).sum()/2))
    record('normalized_weight_bound_half_l1',worst,200)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(dict(seed=20260908,scope='floating-point checks, not end-to-end rendering guarantees',checks=checks),indent=2)+'\n')
    print(json.dumps(checks,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=Path('math_results.json'));main(parser.parse_args().out)
