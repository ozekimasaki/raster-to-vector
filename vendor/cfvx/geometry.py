"""Primitive fitting and contour model selection.

Search order follows the review §10.1: line / circle / arc, then cubic
Bezier. Circle-first is a search policy, not a fidelity override.

Arc fitting keeps endpoints on the contour (G0) by constraining the
center to the chord perpendicular bisector (§9.4, §11.4).
Short arcs use sagitta / curvature rather than a far-away center (§9.5–9.6).
Candidate failure of a least-squares solver is `unknown`, not certified
infeasible (§10.2).
"""
from __future__ import annotations

import math
import numpy as np
from scipy.optimize import least_squares

from .types import ArcSeg, CandidateStatus, CubicSeg, LineSeg, Segment, Vec2

_EPS_H = 1e-9


def _as_xy(pts: np.ndarray) -> np.ndarray:
    arr = np.asarray(pts, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError("points must be (N, 2)")
    return arr


def _vec(p: np.ndarray) -> Vec2:
    return (float(p[0]), float(p[1]))


def _dist_to_segment(pts: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    L2 = float(np.dot(ab, ab))
    if L2 < _EPS_H:
        return np.linalg.norm(pts - a, axis=1)
    t = np.clip(((pts - a) @ ab) / L2, 0.0, 1.0)
    proj = a + np.outer(t, ab)
    return np.linalg.norm(pts - proj, axis=1)


def line_max_error(pts: np.ndarray) -> float:
    if len(pts) < 2:
        return 0.0
    return float(np.max(_dist_to_segment(pts, pts[0], pts[-1])))


def fit_line(pts: np.ndarray, eps: float) -> tuple[LineSeg | None, float, CandidateStatus]:
    pts = _as_xy(pts)
    if len(pts) < 2:
        return None, math.inf, "unknown"
    err = line_max_error(pts)
    seg = LineSeg(start=_vec(pts[0]), end=_vec(pts[-1]))
    if err <= eps:
        return seg, err, "feasible"
    return None, err, "unknown"


def _kasa_circle(pts: np.ndarray) -> np.ndarray | None:
    x, y = pts[:, 0], pts[:, 1]
    xm, ym = float(x.mean()), float(y.mean())
    u, v = x - xm, y - ym
    A = np.column_stack([2 * u, 2 * v, np.ones(len(pts))])
    b = u * u + v * v
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy, c = (float(sol[0]), float(sol[1]), float(sol[2]))
    r2 = c + cx * cx + cy * cy
    if r2 <= _EPS_H or not math.isfinite(r2):
        return None
    return np.array([cx + xm, cy + ym, math.sqrt(r2)], dtype=np.float64)


def fit_full_circle(
    pts: np.ndarray, eps: float
) -> tuple[ArcSeg | None, float, CandidateStatus]:
    """Closed-contour circle. Emitted as a 2π arc; serializer splits it."""
    pts = _as_xy(pts)
    if len(pts) < 6:
        return None, math.inf, "unknown"
    init = _kasa_circle(pts)
    if init is None:
        return None, math.inf, "unknown"

    def resid(p: np.ndarray) -> np.ndarray:
        return np.linalg.norm(pts - p[:2], axis=1) - p[2]

    try:
        fit = least_squares(resid, init, method="lm", ftol=1e-12, xtol=1e-12, max_nfev=80)
        cx, cy, r = (float(fit.x[0]), float(fit.x[1]), float(fit.x[2]))
    except Exception:
        cx, cy, r = (float(init[0]), float(init[1]), float(init[2]))
    if not (math.isfinite(r) and r > 0.5):
        return None, math.inf, "unknown"
    err = float(np.max(np.abs(np.linalg.norm(pts - np.array([cx, cy]), axis=1) - r)))
    if err > eps:
        return None, err, "unknown"
    p0 = pts[0]
    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    start = (cx + r * math.cos(a0), cy + r * math.sin(a0))
    seg = ArcSeg(
        center=(cx, cy),
        radius=r,
        start_angle=a0,
        signed_sweep=2.0 * math.pi,
        start=start,
        end=start,
    )
    return seg, err, "feasible"


def _arc_from_h(
    p0: np.ndarray, p1: np.ndarray, h: float, n: np.ndarray
) -> tuple[np.ndarray, float, float, float] | None:
    mid = 0.5 * (p0 + p1)
    chord = p1 - p0
    length = float(np.hypot(chord[0], chord[1]))
    c = mid + h * n
    r = math.hypot(length * 0.5, h)
    if r < 0.4 or not math.isfinite(r):
        return None
    a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
    a1 = math.atan2(p1[1] - c[1], p1[0] - c[0])
    # Sweep that stays consistent with center side.
    # Image coords (y down): n is left of chord (inward for CCW contours).
    sweep = a1 - a0
    sweep = (sweep + math.pi) % (2 * math.pi) - math.pi
    # If h is the offset of the center along n, minor-arc centers sit
    # opposite the bulge. Choose the sweep whose interior matches the bulge.
    # Bulge is opposite the center for |sweep| < pi.
    # Cross product of chord and (midpoint-on-arc - mid_chord) should match.
    mid_ang = a0 + 0.5 * sweep
    arc_mid = c + r * np.array([math.cos(mid_ang), math.sin(mid_ang)])
    bulge_vec = arc_mid - mid
    # We want the arc midpoint on the same side as the data, handled by caller.
    if abs(h) < 1e-8:
        return None
    # If the current sweep's midpoint is on the same side as the center (h>0
    # means center along +n), the midpoint of a minor arc is on -n.
    side = float(np.dot(bulge_vec, n))
    if (h < 0 and side < 0) or (h > 0 and side > 0):
        if sweep > 0:
            sweep -= 2 * math.pi
        else:
            sweep += 2 * math.pi
        mid_ang = a0 + 0.5 * sweep
    return c, r, a0, sweep


def fit_arc(pts: np.ndarray, eps: float) -> tuple[ArcSeg | None, float, CandidateStatus]:
    pts = _as_xy(pts)
    if len(pts) < 3:
        return None, math.inf, "unknown"
    p0, p1 = pts[0], pts[-1]
    chord = p1 - p0
    length = float(np.hypot(chord[0], chord[1]))
    if length < 1e-6:
        return None, math.inf, "unknown"
    t = chord / length
    n = np.array([-t[1], t[0]], dtype=np.float64)
    rel = pts - p0
    signed = rel @ n
    sag = float(signed[np.argmax(np.abs(signed))])
    if abs(sag) < 1e-6:
        return None, abs(sag), "unknown"
    r0 = abs(sag) * 0.5 + (length * length) / (8.0 * abs(sag))
    h0 = -math.copysign(r0 - abs(sag), sag)

    def resid(h_arr: np.ndarray) -> np.ndarray:
        h = float(h_arr[0])
        c = 0.5 * (p0 + p1) + h * n
        r = math.hypot(length * 0.5, h)
        return np.linalg.norm(pts - c, axis=1) - r

    h = h0
    try:
        fit = least_squares(resid, np.array([h0]), ftol=1e-12, xtol=1e-12, max_nfev=60)
        if fit.success or np.max(np.abs(fit.fun)) < np.max(np.abs(resid(np.array([h0])))):
            h = float(fit.x[0])
    except Exception:
        h = h0

    built = _arc_from_h(p0, p1, h, n)
    if built is None:
        return None, math.inf, "unknown"
    c, r, a0, sweep = built
    if abs(sweep) < 1e-3 or abs(sweep) > 2 * math.pi * 0.999:
        return None, math.inf, "unknown"
    if r > 1.0e5:
        return None, math.inf, "unknown"

    # Finite-arc distance (§9.4), not full-circle radial distance.
    err = _finite_arc_max_error(pts, c, r, a0, sweep)
    # Endpoints must stay on the contour vertices for G0.
    seg = ArcSeg(
        center=(float(c[0]), float(c[1])),
        radius=float(r),
        start_angle=float(a0),
        signed_sweep=float(sweep),
        start=_vec(p0),
        end=_vec(p1),
    )
    # Also require points to lie near the arc, not the complementary circle.
    if err <= eps:
        return seg, err, "feasible"
    return None, err, "unknown"


def _finite_arc_max_error(
    pts: np.ndarray, c: np.ndarray, r: float, a0: float, sweep: float
) -> float:
    v = pts - c
    ang = np.arctan2(v[:, 1], v[:, 0])
    if sweep >= 0:
        rel = (ang - a0) % (2 * math.pi)
        on = rel <= sweep + 1e-6
    else:
        rel = (a0 - ang) % (2 * math.pi)
        on = rel <= (-sweep) + 1e-6
    radial = np.abs(np.linalg.norm(v, axis=1) - r)
    p_start = c + r * np.array([math.cos(a0), math.sin(a0)])
    p_end = c + r * np.array([math.cos(a0 + sweep), math.sin(a0 + sweep)])
    d_end = np.minimum(
        np.linalg.norm(pts - p_start, axis=1),
        np.linalg.norm(pts - p_end, axis=1),
    )
    dist = np.where(on, radial, d_end)
    # If too few points project onto the finite arc, reject.
    if float(np.mean(on)) < 0.8:
        return float(np.max(dist) + 10.0)
    return float(np.max(dist))


def _chord_params(pts: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.sum(np.diff(pts, axis=0) ** 2, axis=1))
    u = np.concatenate([[0.0], np.cumsum(d)])
    if u[-1] < 1e-12:
        return np.linspace(0.0, 1.0, len(pts))
    return u / u[-1]


def fit_cubic(pts: np.ndarray, eps: float) -> tuple[CubicSeg | None, float, CandidateStatus]:
    pts = _as_xy(pts)
    if len(pts) < 4:
        return None, math.inf, "unknown"
    p0, p3 = pts[0], pts[-1]
    t = _chord_params(pts)
    t2, t3 = t * t, t * t * t
    u = 1.0 - t
    u2, u3 = u * u, u * u * u
    a1 = 3.0 * u2 * t
    a2 = 3.0 * u * t2
    b = pts - np.outer(u3, p0) - np.outer(t3, p3)
    n = len(pts)
    A = np.zeros((2 * n, 4), dtype=np.float64)
    A[0::2, 0] = a1
    A[0::2, 2] = a2
    A[1::2, 1] = a1
    A[1::2, 3] = a2
    try:
        sol, *_ = np.linalg.lstsq(A, b.reshape(-1), rcond=None)
    except np.linalg.LinAlgError:
        return None, math.inf, "unknown"
    c1 = np.array([sol[0], sol[1]], dtype=np.float64)
    c2 = np.array([sol[2], sol[3]], dtype=np.float64)
    pred = (
        np.outer(u3, p0)
        + np.outer(a1, c1)
        + np.outer(a2, c2)
        + np.outer(t3, p3)
    )
    err = float(np.max(np.linalg.norm(pred - pts, axis=1)))
    seg = CubicSeg(
        points=(_vec(p0), _vec(c1), _vec(c2), _vec(p3)),
    )
    if err <= eps:
        return seg, err, "feasible"
    return None, err, "unknown"


def _cost(kind: str, err: float, eps: float) -> float:
    # §5.4 description complexity: prefer fewer segments, then fewer DOF.
    # A feasible long arc must beat a chain of short lines (handled because
    # we accept a primitive for the whole span when it is feasible).
    dof = {"line": 0.0, "arc": 1.0, "cubic": 4.0}[kind]
    return 1.0 + 0.25 * dof + 0.05 * (err / max(eps, 1e-6))


def _best_primitive(pts: np.ndarray, eps: float) -> tuple[Segment | None, float]:
    candidates: list[tuple[float, Segment, float]] = []
    line, lerr, lst = fit_line(pts, eps)
    if lst == "feasible" and line is not None:
        candidates.append((_cost("line", lerr, eps), line, lerr))
    arc, aerr, ast = fit_arc(pts, eps)
    if ast == "feasible" and arc is not None:
        candidates.append((_cost("arc", aerr, eps), arc, aerr))
    cubic, cerr, cst = fit_cubic(pts, eps)
    if cst == "feasible" and cubic is not None:
        candidates.append((_cost("cubic", cerr, eps), cubic, cerr))
    if not candidates:
        return None, min(lerr, aerr, cerr)
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1], candidates[0][2]


def _max_chord_index(pts: np.ndarray) -> int:
    if len(pts) < 3:
        return len(pts) // 2
    d = _dist_to_segment(pts, pts[0], pts[-1])
    d[0] = -1.0
    d[-1] = -1.0
    k = int(np.argmax(d))
    if k <= 0 or k >= len(pts) - 1:
        k = len(pts) // 2
    return k


def _turning_corners(pts: np.ndarray, closed: bool, angle_deg: float) -> list[int]:
    n = len(pts)
    if n < 5:
        return []
    w = 2
    corners: list[int] = []
    thresh = math.radians(angle_deg)
    for i in range(n):
        if not closed and (i < w or i >= n - w):
            continue
        a = pts[(i - w) % n]
        b = pts[i]
        c = pts[(i + w) % n]
        v1 = b - a
        v2 = c - b
        n1 = float(np.hypot(v1[0], v1[1]))
        n2 = float(np.hypot(v2[0], v2[1]))
        if n1 < 1e-9 or n2 < 1e-9:
            continue
        cross = abs(v1[0] * v2[1] - v1[1] * v2[0]) / (n1 * n2)
        dot = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
        ang = math.atan2(cross, dot)
        if ang >= thresh:
            corners.append(i)
    # Keep corners at least 3 samples apart.
    if not corners:
        return []
    kept: list[int] = [corners[0]]
    for i in corners[1:]:
        if i - kept[-1] >= 3:
            kept.append(i)
    if closed and kept and (kept[0] + n - kept[-1]) < 3 and len(kept) > 1:
        kept.pop()
    return kept


def _polyline_fallback(pts: np.ndarray) -> list[Segment]:
    return [
        LineSeg(start=_vec(pts[i]), end=_vec(pts[i + 1]))
        for i in range(len(pts) - 1)
        if not np.allclose(pts[i], pts[i + 1])
    ]


def _resample(pts: np.ndarray, spacing: float = 0.85) -> np.ndarray:
    closed = np.allclose(pts[0], pts[-1], atol=1e-9)
    src = pts[:-1] if closed else pts
    if len(src) < 3:
        return pts
    d = np.sqrt(np.sum(np.diff(np.vstack([src, src[0] if closed else src[-1]]), axis=0) ** 2, axis=1))
    if not closed:
        d = np.sqrt(np.sum(np.diff(src, axis=0) ** 2, axis=1))
        u = np.concatenate([[0.0], np.cumsum(d)])
        if u[-1] < spacing * 2:
            return pts
        n = max(int(math.ceil(u[-1] / spacing)), 2)
        t = np.linspace(0.0, u[-1], n)
        x = np.interp(t, u, src[:, 0])
        y = np.interp(t, u, src[:, 1])
        return np.column_stack([x, y])
    d = np.sqrt(np.sum(np.diff(np.vstack([src, src[0]]), axis=0) ** 2, axis=1))
    u = np.concatenate([[0.0], np.cumsum(d)])
    if u[-1] < spacing * 3:
        return pts
    n = max(int(math.ceil(u[-1] / spacing)), 4)
    t = np.linspace(0.0, u[-1], n, endpoint=False)
    x = np.interp(t, u, np.append(src[:, 0], src[0, 0]))
    y = np.interp(t, u, np.append(src[:, 1], src[0, 1]))
    out = np.column_stack([x, y])
    return np.vstack([out, out[0]])


def fit_contour(
    pts: np.ndarray,
    eps: float,
    closed: bool = True,
    corner_angle_deg: float = 42.0,
) -> tuple[list[Segment], float]:
    """Fit a contour with circle-first model selection.

    Uses hard splits at sharp corners, then recursive span fitting
    (heuristic search in the sense of §10.5, not certified global DP).
    """
    pts = _resample(_as_xy(pts))
    if closed:
        if len(pts) >= 2 and np.allclose(pts[0], pts[-1], atol=1e-9):
            pts = pts[:-1]
        if len(pts) >= 3:
            circ, cerr, cst = fit_full_circle(np.vstack([pts, pts[0]]), eps)
            if cst == "feasible" and circ is not None:
                return [circ], cerr
        pts_c = np.vstack([pts, pts[0]])
    else:
        pts_c = pts

    if len(pts_c) < 2:
        return [], 0.0

    n_unique = len(pts_c) - (1 if closed else 0)
    corners = _turning_corners(pts if closed else pts_c, closed, corner_angle_deg)
    anchors = [0]
    for c in corners:
        if 0 < c < n_unique:
            anchors.append(c)
    if closed:
        anchors.append(n_unique)
    else:
        if anchors[-1] != len(pts_c) - 1:
            anchors.append(len(pts_c) - 1)
    anchors = sorted(set(anchors))

    segs: list[Segment] = []
    max_err = 0.0

    def rec(i: int, j: int, depth: int) -> list[Segment]:
        nonlocal max_err
        span = pts_c[i : j + 1]
        if len(span) < 2:
            return []
        if j - i <= 1:
            max_err = max(max_err, 0.0)
            return [LineSeg(start=_vec(span[0]), end=_vec(span[-1]))]
        prim, err = _best_primitive(span, eps)
        if prim is not None:
            max_err = max(max_err, err)
            return [prim]
        if depth > 18 or j - i <= 3:
            fb = _polyline_fallback(span)
            max_err = max(max_err, line_max_error(span))
            return fb
        k_local = _max_chord_index(span)
        k = i + k_local
        if k <= i or k >= j:
            k = (i + j) // 2
        return rec(i, k, depth + 1) + rec(k, j, depth + 1)

    for a, b in zip(anchors[:-1], anchors[1:]):
        if b <= a:
            continue
        segs.extend(rec(a, b, 0))

    segs = _merge_colinear(segs, eps)
    return segs, max_err


def _merge_colinear(segs: list[Segment], eps: float) -> list[Segment]:
    if not segs:
        return segs
    out: list[Segment] = [segs[0]]
    for s in segs[1:]:
        prev = out[-1]
        if prev.kind == "line" and s.kind == "line":
            pts = np.array([prev.start, prev.end, s.end], dtype=np.float64)
            if line_max_error(pts) <= eps:
                out[-1] = LineSeg(start=prev.start, end=s.end)
                continue
        out.append(s)
    return out


def sample_segment(seg: Segment, n: int = 24) -> np.ndarray:
    if seg.kind == "line":
        return np.array([seg.start, seg.end], dtype=np.float64)
    if seg.kind == "arc":
        arc_len = abs(seg.signed_sweep) * max(seg.radius, 1.0)
        n_use = max(n, int(math.ceil(arc_len / 0.35)) + 1)
        if abs(seg.signed_sweep) >= 2 * math.pi * 0.99:
            angs = np.linspace(seg.start_angle, seg.start_angle + 2 * math.pi, max(n_use, 48), endpoint=True)
            c = np.array(seg.center)
            return c + seg.radius * np.column_stack([np.cos(angs), np.sin(angs)])
        angs = np.linspace(seg.start_angle, seg.start_angle + seg.signed_sweep, max(n_use, 8))
        c = np.array(seg.center)
        pts = c + seg.radius * np.column_stack([np.cos(angs), np.sin(angs)])
        pts[0] = seg.start
        pts[-1] = seg.end
        return pts
    p0, p1, p2, p3 = (np.array(p, dtype=np.float64) for p in seg.points)
    t = np.linspace(0.0, 1.0, max(n, 8))
    u = 1.0 - t
    return (
        np.outer(u**3, p0)
        + np.outer(3 * u**2 * t, p1)
        + np.outer(3 * u * t**2, p2)
        + np.outer(t**3, p3)
    )


def path_to_polygon(segs: list[Segment], n_per: int = 20) -> np.ndarray:
    if not segs:
        return np.zeros((0, 2), dtype=np.float64)
    chunks = [sample_segment(segs[0], n_per)]
    for s in segs[1:]:
        pts = sample_segment(s, n_per)
        chunks.append(pts[1:])
    poly = np.vstack(chunks)
    if not np.allclose(poly[0], poly[-1]):
        poly = np.vstack([poly, poly[0]])
    return poly


def polygon_area(poly: np.ndarray) -> float:
    if len(poly) < 3:
        return 0.0
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def reverse_segments(segs: list[Segment]) -> list[Segment]:
    out: list[Segment] = []
    for s in reversed(segs):
        if s.kind == "line":
            out.append(LineSeg(start=s.end, end=s.start))
        elif s.kind == "arc":
            out.append(
                ArcSeg(
                    center=s.center,
                    radius=s.radius,
                    start_angle=s.start_angle + s.signed_sweep,
                    signed_sweep=-s.signed_sweep,
                    start=s.end,
                    end=s.start,
                )
            )
        else:
            p0, c1, c2, p3 = s.points
            out.append(CubicSeg(points=(p3, c2, c1, p0)))
    return out


def rdp(pts: np.ndarray, eps: float) -> np.ndarray:
    pts = _as_xy(pts)
    closed = len(pts) >= 2 and np.allclose(pts[0], pts[-1], atol=1e-9)
    src = pts[:-1] if closed else pts
    if len(src) < 3:
        return pts

    stack = [(0, len(src) - 1)]
    keep = {0, len(src) - 1}
    while stack:
        i, j = stack.pop()
        if j - i <= 1:
            continue
        d = _dist_to_segment(src[i : j + 1], src[i], src[j])
        k = int(np.argmax(d))
        if d[k] > eps and k not in (0, j - i):
            mid = i + k
            keep.add(mid)
            stack.append((i, mid))
            stack.append((mid, j))
    idx = sorted(keep)
    out = src[np.array(idx, dtype=int)]
    if closed:
        out = np.vstack([out, out[0]])
    return out


def contour_as_polyline(pts: np.ndarray, eps: float) -> list[Segment]:
    simp = rdp(pts, max(eps, 0.25))
    if np.allclose(simp[0], simp[-1], atol=1e-9):
        simp = simp[:-1]
    if len(simp) < 2:
        return []
    segs = [
        LineSeg(start=_vec(simp[i]), end=_vec(simp[(i + 1) % len(simp)]))
        for i in range(len(simp))
    ]
    return segs
