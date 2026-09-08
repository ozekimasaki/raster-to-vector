"""SVG serializer and sidecar.

Internal geometry stays in center/radius/Bezier form; SVG is a derived
artifact (§15.1). Full circles are two arcs, never a zero-length A (§15.3).
Shared endpoints reuse the same numeric string (§15.5, simplified).
"""
from __future__ import annotations

import math
from xml.sax.saxutils import escape

from .types import ArcSeg, ColorLayer, CubicSeg, LineSeg, Scene, Segment


def _fmt(x: float, cache: dict[tuple[float, float], str] | None = None) -> str:
    # 3 decimals is ~0.001px, well below the source-pixel tolerance. This is
    # a fixed rounding policy, not a certified adaptive budget (§15.5).
    v = 0.0 if abs(x) < 5e-5 else x
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    if s in ("", "-"):
        s = "0"
    return s


def _pt(p: tuple[float, float]) -> str:
    return f"{_fmt(p[0])},{_fmt(p[1])}"


def _seg_to_d(seg: Segment, start_needed: bool) -> str:
    parts: list[str] = []
    if seg.kind == "line":
        if start_needed:
            parts.append(f"M{_pt(seg.start)}")
        parts.append(f"L{_pt(seg.end)}")
        return "".join(parts)
    if seg.kind == "arc":
        if start_needed:
            parts.append(f"M{_pt(seg.start)}")
        r = _fmt(seg.radius)
        sweep = 1 if seg.signed_sweep > 0 else 0
        if abs(seg.signed_sweep) >= 2 * math.pi * 0.99:
            # Two half-arcs. Image/SVG y-down: positive atan2 is clockwise
            # on screen, which is SVG sweep-flag=1.
            cx, cy = seg.center
            a0 = seg.start_angle
            mid_ang = a0 + math.pi
            mid = (cx + seg.radius * math.cos(mid_ang), cy + seg.radius * math.sin(mid_ang))
            end = (cx + seg.radius * math.cos(a0 + 2 * math.pi), cy + seg.radius * math.sin(a0 + 2 * math.pi))
            parts.append(f"A{r},{r} 0 1 {sweep} {_pt(mid)}")
            parts.append(f"A{r},{r} 0 1 {sweep} {_pt(end)}")
            return "".join(parts)
        large = 1 if abs(seg.signed_sweep) > math.pi else 0
        parts.append(f"A{r},{r} 0 {large} {sweep} {_pt(seg.end)}")
        return "".join(parts)
    p0, c1, c2, p3 = seg.points
    if start_needed:
        parts.append(f"M{_pt(p0)}")
    parts.append(f"C{_pt(c1)} {_pt(c2)} {_pt(p3)}")
    return "".join(parts)


def _path_d(segs: list[Segment]) -> str:
    if not segs:
        return ""
    d = [_seg_to_d(segs[0], start_needed=True)]
    for s in segs[1:]:
        d.append(_seg_to_d(s, start_needed=False))
    d.append("Z")
    return "".join(d)


def _hex(rgba: tuple[int, int, int, int]) -> str:
    return f"#{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}"


def scene_to_svg(scene: Scene, title: str | None = None) -> str:
    w, h = scene.width, scene.height
    vb = scene.view_box
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{w}" height="{h}" viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}" '
            f'fill-rule="nonzero">'
        ),
    ]
    if title:
        lines.append(f"<title>{escape(title)}</title>")
    lines.append(
        "<!-- CFV-X faithful vectorization. Strict vector: no embedded raster. -->"
    )
    for i, layer in enumerate(scene.layers):
        if not layer.paths:
            continue
        fill = _hex(layer.rgba)
        opacity = layer.rgba[3] / 255.0
        extra = ""
        if opacity < 1.0 - 1e-6:
            extra = f' fill-opacity="{_fmt(opacity)}"'
        gid = f"layer{i:02d}_{fill[1:]}"
        role = "outline" if layer.is_outline else "fill"
        lines.append(f'<g id="{gid}" data-cfvx-role="{role}" fill="{fill}" stroke="none"{extra}>')
        for path in layer.paths:
            d = _path_d(path.outer)
            for hole in path.holes:
                hd = _path_d(hole)
                if hd:
                    # evenodd: extra closed subpath punches a hole
                    d += hd
            if d:
                lines.append(f'<path d="{d}"/>')
        lines.append("</g>")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def primitive_counts(scene: Scene) -> dict[str, int]:
    counts = {"line": 0, "arc": 0, "cubic": 0, "circle": 0}
    for layer in scene.layers:
        for path in layer.paths:
            for segs in [path.outer, *path.holes]:
                for s in segs:
                    if s.kind == "arc" and abs(s.signed_sweep) >= 2 * math.pi * 0.99:
                        counts["circle"] += 1
                    else:
                        counts[s.kind] += 1
    return counts
