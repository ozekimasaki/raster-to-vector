"""Compose SVG and shared-boundary JSON from one fitted segment cache."""
from __future__ import annotations

from xml.sax.saxutils import escape

from .fit import Fitted, fmt_num, oriented, path_d
from .graph import BoundaryGraph, SegRef, contour_points, shoelace


def _hex_rgb(rgb) -> str:
    r, g, b = (int(max(0, min(255, round(v)))) for v in rgb[:3])
    return f'#{r:02x}{g:02x}{b:02x}'


def contour_d(graph: BoundaryGraph, contour: list[SegRef], fitted: list[Fitted]) -> str:
    if not contour:
        return ''
    parts = []
    for i, ref in enumerate(contour):
        geom = oriented(fitted[ref.seg], ref.forward)
        parts.append(path_d(geom, move=(i == 0)))
    return ''.join(parts) + 'Z'


def face_path_d(graph: BoundaryGraph, contours: list[list[SegRef]], fitted: list[Fitted]) -> str:
    return ''.join(contour_d(graph, contour, fitted) for contour in contours)


def shared_coord_text(fitted: Fitted, forward: bool = True) -> str:
    geom = oriented(fitted, forward)
    return f'{fmt_num(geom.start[0])} {fmt_num(geom.start[1])}' + ''.join(
        f' {fmt_num(v)}' for op in geom.ops for v in op[1:] if isinstance(v, float)
    )


def reversal_pairs_match(graph: BoundaryGraph, faces: dict, fitted: list[Fitted]) -> bool:
    for item in fitted:
        if shared_coord_text(item, False) != shared_coord_text(oriented(item, False), True):
            return False
        twice = oriented(oriented(item, False), False)
        if shared_coord_text(twice, True) != shared_coord_text(item, True):
            return False
    used = {seg_id: 0 for seg_id in range(len(graph.segments))}
    for contours in faces.values():
        for contour in contours:
            for ref in contour:
                used[ref.seg] += 1
                if used[ref.seg] > 2:
                    return False
    return True


def compose_svg(
    graph: BoundaryGraph,
    faces: dict,
    fitted: list[Fitted],
    paints: dict,
    title: str | None = None,
) -> str:
    w, h = graph.width, graph.height
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" fill-rule="nonzero">'
        ),
    ]
    if title:
        lines.append(f'<title>{escape(title)}</title>')
    lines.append('<!-- mosaic-draft: shared crack boundaries. Not a final quality certificate. -->')
    for region in sorted(faces):
        d = face_path_d(graph, faces[region], fitted)
        if not d:
            continue
        rgb = paints.get(region, (128, 128, 128, 255))
        fill = _hex_rgb(rgb)
        extra = ''
        if len(rgb) > 3 and rgb[3] < 255:
            extra = f' fill-opacity="{fmt_num(rgb[3] / 255.0)}"'
        lines.append(
            f'<path id="region_{region}" fill="{fill}" stroke="none" fill-rule="nonzero"{extra} d="{d}"/>'
        )
    lines.append('</svg>')
    return '\n'.join(lines) + '\n'


def shared_boundary_json(graph: BoundaryGraph, faces: dict, fitted: list[Fitted], paints: dict) -> dict:
    vertices = {f'n{i}': [node.x, node.y] for i, node in enumerate(graph.nodes)}
    # Rings have no junction; record a synthetic vertex at the first point.
    ring_vertices = {}
    edges = {}
    for i, seg in enumerate(graph.segments):
        kind = 'ring' if seg.is_ring else 'open'
        backend = fitted[i].backend
        geom_kind = 'polyline'
        if any(op[0] == 'C' for op in fitted[i].ops):
            geom_kind = 'cubic'
        elif any(op[0] == 'A' for op in fitted[i].ops):
            geom_kind = 'arc'
        start_key = f'n{seg.start}' if seg.start is not None else f'r{i}'
        end_key = f'n{seg.end}' if seg.end is not None else f'r{i}'
        if seg.is_ring:
            ring_vertices[f'r{i}'] = [seg.points[0][0], seg.points[0][1]]
        edges[f'e{i}'] = {
            'kind': geom_kind,
            'role': kind,
            'backend': backend,
            'start': start_key,
            'end': end_key,
            'left': seg.left,
            'right': seg.right,
            'forward_d': path_d(fitted[i], move=True),
            'reverse_d': path_d(oriented(fitted[i], False), move=True),
        }
    vertices.update(ring_vertices)

    out_faces = {}
    for region, contours in faces.items():
        loops = []
        holes = []
        for contour in contours:
            loop = [[f'e{ref.seg}', 1 if ref.forward else -1] for ref in contour]
            area = -shoelace(contour_points(graph, contour))
            item = {'loop': loop, 'signed_area': area}
            if area < 0:
                holes.append(item)
            else:
                loops.append(item)
        rgb = paints.get(region, (128, 128, 128, 255))
        primary = loops[0]['loop'] if loops else (holes[0]['loop'] if holes else [])
        extra = [item['loop'] for item in loops[1:]]
        out_faces[f'r{region}'] = {
            'loop': primary,
            'holes': [item['loop'] for item in holes],
            'extra_outers': extra,
            'fill': _hex_rgb(rgb),
        }
    return {
        'description': (
            'Mosaic shared-boundary graph. Each edge is fitted once; faces reference '
            'the same geometry with t or 1-t. Draft only, not a general DCEL.'
        ),
        'width': graph.width,
        'height': graph.height,
        'vertices': vertices,
        'edges': edges,
        'faces': out_faces,
        'holes': [],
        'unresolved': [],
    }
