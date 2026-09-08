"""Once-per-segment fitters with pinned endpoints.

pixel: lattice identity. polygon: symmetric open Douglas-Peucker.
curve: optional CFV-X line/arc/cubic on the simplified open polyline.
Neighbors share one Fitted object; reversal is exact.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .graph import BoundaryGraph, Segment

DEFAULT_TAU = 0.5


@dataclass
class Fitted:
    start: tuple[float, float]
    end: tuple[float, float]
    ops: list = field(default_factory=list)
    backend: str = 'pixel'
    closed: bool = False


def fmt_num(value: float, precision: int = 3) -> str:
    v = 0.0 if abs(value) < 5e-5 else float(value)
    rounded = round(v)
    if abs(v - rounded) < 10 ** (-precision):
        return str(int(rounded))
    text = f'{v:.{precision}f}'.rstrip('0').rstrip('.')
    if text in ('', '-'):
        return '0'
    return text


def _pt(x: float, y: float) -> str:
    return f'{fmt_num(x)} {fmt_num(y)}'


def dist_to_segment(pts: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    length = float(np.dot(ab, ab))
    if length < 1e-18:
        return np.linalg.norm(pts - a, axis=1)
    t = np.clip(((pts - a) @ ab) / length, 0.0, 1.0)
    proj = a + np.outer(t, ab)
    return np.linalg.norm(pts - proj, axis=1)


def douglas_peucker(pts: np.ndarray, tau: float) -> np.ndarray:
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) <= 2:
        return pts
    d = dist_to_segment(pts, pts[0], pts[-1])
    d[0] = -1.0
    d[-1] = -1.0
    i = int(np.argmax(d))
    if i <= 0 or i >= len(pts) - 1 or float(d[i]) <= tau:
        return np.vstack([pts[0], pts[-1]])
    left = douglas_peucker(pts[: i + 1], tau)
    right = douglas_peucker(pts[i:], tau)
    return np.vstack([left[:-1], right])


def simplify_polyline(points: list, tau: float, closed: bool) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64)
    if closed and len(pts) >= 2 and np.allclose(pts[0], pts[-1]):
        pts = pts
    if len(pts) <= 2:
        return pts
    return douglas_peucker(pts, tau)


def polyline_fitted(points: list, backend: str, closed: bool = False) -> Fitted:
    seq = [(float(p[0]), float(p[1])) for p in points]
    if closed and seq and seq[0] != seq[-1]:
        seq.append(seq[0])
    if len(seq) < 2:
        start = seq[0] if seq else (0.0, 0.0)
        return Fitted(start=start, end=start, ops=[], backend=backend, closed=closed)
    ops = [('L', x, y) for x, y in seq[1:]]
    return Fitted(start=seq[0], end=seq[-1], ops=ops, backend=backend, closed=closed)


def reverse_fitted(fitted: Fitted) -> Fitted:
    pos = [fitted.start]
    for op in fitted.ops:
        if op[0] == 'L':
            pos.append((op[1], op[2]))
        elif op[0] == 'C':
            pos.append((op[5], op[6]))
        else:
            pos.append((op[6], op[7]))
    new_ops = []
    for i in range(len(fitted.ops) - 1, -1, -1):
        op = fitted.ops[i]
        dest = pos[i]
        if op[0] == 'L':
            new_ops.append(('L', dest[0], dest[1]))
        elif op[0] == 'C':
            new_ops.append(('C', op[3], op[4], op[1], op[2], dest[0], dest[1]))
        else:
            new_ops.append(('A', op[1], op[2], op[3], op[4], 1 - op[5], dest[0], dest[1]))
    return Fitted(start=fitted.end, end=fitted.start, ops=new_ops, backend=fitted.backend, closed=fitted.closed)


def pin_endpoints(fitted: Fitted, start: tuple, end: tuple) -> Fitted:
    fitted.start = (float(start[0]), float(start[1]))
    if not fitted.ops:
        fitted.end = (float(end[0]), float(end[1]))
        return fitted
    op = fitted.ops[-1]
    if op[0] == 'L':
        fitted.ops[-1] = ('L', float(end[0]), float(end[1]))
    elif op[0] == 'C':
        fitted.ops[-1] = ('C', op[1], op[2], op[3], op[4], float(end[0]), float(end[1]))
    else:
        fitted.ops[-1] = ('A', op[1], op[2], op[3], op[4], op[5], float(end[0]), float(end[1]))
    fitted.end = (float(end[0]), float(end[1]))
    return fitted


def ops_text(fitted: Fitted) -> str:
    parts = []
    for op in fitted.ops:
        if op[0] == 'L':
            parts.append(f'L{_pt(op[1], op[2])}')
        elif op[0] == 'C':
            parts.append(f'C{_pt(op[1], op[2])} {_pt(op[3], op[4])} {_pt(op[5], op[6])}')
        else:
            parts.append(
                f'A{fmt_num(op[1])} {fmt_num(op[2])} {fmt_num(op[3])} {int(op[4])} {int(op[5])} {_pt(op[6], op[7])}'
            )
    return ''.join(parts)


def path_d(fitted: Fitted, move: bool = True) -> str:
    start = f'M{_pt(*fitted.start)}' if move else ''
    return start + ops_text(fitted)


def _cfvx_segments_to_fitted(segs, backend: str, closed: bool) -> Fitted:
    if not segs:
        return Fitted(start=(0.0, 0.0), end=(0.0, 0.0), ops=[], backend=backend, closed=closed)
    first = segs[0]
    if first.kind == 'line':
        start = (float(first.start[0]), float(first.start[1]))
    elif first.kind == 'arc':
        start = (float(first.start[0]), float(first.start[1]))
    else:
        start = (float(first.points[0][0]), float(first.points[0][1]))
    ops = []
    end = start
    for seg in segs:
        if seg.kind == 'line':
            end = (float(seg.end[0]), float(seg.end[1]))
            ops.append(('L', end[0], end[1]))
        elif seg.kind == 'arc':
            radius = float(seg.radius)
            sweep_flag = 1 if seg.signed_sweep > 0 else 0
            if abs(seg.signed_sweep) >= 2 * math.pi * 0.99:
                cx, cy = float(seg.center[0]), float(seg.center[1])
                a0 = float(seg.start_angle)
                mid = (cx + radius * math.cos(a0 + math.pi), cy + radius * math.sin(a0 + math.pi))
                end = (cx + radius * math.cos(a0 + 2 * math.pi), cy + radius * math.sin(a0 + 2 * math.pi))
                ops.append(('A', radius, radius, 0.0, 1, sweep_flag, mid[0], mid[1]))
                ops.append(('A', radius, radius, 0.0, 1, sweep_flag, end[0], end[1]))
            else:
                large = 1 if abs(seg.signed_sweep) > math.pi else 0
                end = (float(seg.end[0]), float(seg.end[1]))
                ops.append(('A', radius, radius, 0.0, large, sweep_flag, end[0], end[1]))
        else:
            _p0, c1, c2, p3 = seg.points
            end = (float(p3[0]), float(p3[1]))
            ops.append(('C', float(c1[0]), float(c1[1]), float(c2[0]), float(c2[1]), end[0], end[1]))
    return Fitted(start=start, end=end, ops=ops, backend=backend, closed=closed)


def _try_curve(points: list, tau: float, closed: bool) -> Fitted | None:
    try:
        from pathlib import Path
        import sys
        vendor = Path(__file__).resolve().parents[3] / 'vendor'
        vendor_s = str(vendor)
        if vendor_s not in sys.path:
            sys.path.insert(0, vendor_s)
        from cfvx.geometry import fit_contour
    except Exception:
        return None
    simple = simplify_polyline(points, tau, closed)
    segs, err = fit_contour(simple, tau, closed=closed)
    if not segs or err > tau + 1e-9:
        return None
    fitted = _cfvx_segments_to_fitted(segs, 'curve', closed)
    if not closed:
        fitted = pin_endpoints(fitted, points[0], points[-1])
    return fitted


def fit_segment(seg: Segment, mode: str, tau: float = DEFAULT_TAU) -> Fitted:
    closed = bool(seg.is_ring)
    points = seg.points
    if mode == 'pixel':
        return polyline_fitted(points, 'pixel', closed=closed)
    if mode == 'curve':
        curved = _try_curve(points, tau, closed)
        if curved is not None:
            return curved
        mode = 'polygon'
    simple = simplify_polyline(points, tau, closed)
    fitted = polyline_fitted(simple.tolist(), 'polygon', closed=closed)
    if not closed:
        fitted = pin_endpoints(fitted, points[0], points[-1])
    else:
        fitted.closed = True
    return fitted


def fit_graph(graph: BoundaryGraph, mode: str, tau: float = DEFAULT_TAU) -> list[Fitted]:
    if mode not in ('pixel', 'polygon', 'curve'):
        raise ValueError('mode must be pixel, polygon, or curve')
    return [fit_segment(seg, mode, tau) for seg in graph.segments]


def oriented(fitted: Fitted, forward: bool) -> Fitted:
    return fitted if forward else reverse_fitted(fitted)
