"""Face assembly from a crack-boundary graph.

Interior stays on the left of every directed segment. Outer contours and
holes therefore get opposite windings without a containment search.
fill-rule nonzero is the matching SVG rule.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .graph import (
    OUTSIDE,
    BoundaryGraph,
    SegRef,
    contour_points,
    extract_graph,
    opposite,
    shoelace,
    successor_dir,
)


def assemble_faces(graph: BoundaryGraph, labels: np.ndarray) -> dict[int, list[list[SegRef]]]:
    faces: dict[int, list[list[SegRef]]] = defaultdict(list)
    used: set[tuple[int, bool]] = set()

    def successor(ref: SegRef) -> SegRef:
        seg = graph.segments[ref.seg]
        if ref.forward:
            node = graph.nodes[seg.end]
            d_in = seg.end_dir
            region = seg.left
        else:
            node = graph.nodes[seg.start]
            d_in = opposite(seg.start_dir)
            region = seg.right
        direction = successor_dir(graph, labels, node.x, node.y, d_in, region)
        nxt = node.out[direction]
        if nxt is None:
            raise RuntimeError(f'Node ({node.x},{node.y}) has no outgoing segment in dir {direction}')
        return nxt

    for seg_id, seg in enumerate(graph.segments):
        if seg.is_ring:
            if seg.left != OUTSIDE:
                faces[seg.left].append([SegRef(seg_id, True)])
            if seg.right != OUTSIDE:
                faces[seg.right].append([SegRef(seg_id, False)])
            continue
        for forward in (True, False):
            region = seg.left if forward else seg.right
            if region == OUTSIDE or (seg_id, forward) in used:
                continue
            start = SegRef(seg_id, forward)
            contour = []
            cur = start
            while True:
                used.add((cur.seg, cur.forward))
                contour.append(cur)
                cur = successor(cur)
                if cur.seg == start.seg and cur.forward == start.forward:
                    break
                if len(contour) > len(graph.segments) * 2 + 2:
                    raise RuntimeError('Face walk did not close')
            faces[region].append(contour)
    return dict(faces)


def region_signed_area(graph: BoundaryGraph, contours: list[list[SegRef]]) -> float:
    # Interior-on-left in y-down yields negative algebraic shoelace for outers.
    # Negating makes outer area positive and holes negative, matching pixel count.
    return -sum(shoelace(contour_points(graph, contour)) for contour in contours)


def pixel_counts(labels: np.ndarray) -> dict[int, int]:
    labels = np.asarray(labels)
    valid = labels != OUTSIDE
    if not np.any(valid):
        return {}
    ids, counts = np.unique(labels[valid], return_counts=True)
    return {int(i): int(c) for i, c in zip(ids, counts)}


def area_matches_pixels(graph: BoundaryGraph, faces: dict, labels: np.ndarray, atol: float = 1e-6) -> bool:
    counts = pixel_counts(labels)
    if set(faces) != set(counts):
        return False
    for region, contours in faces.items():
        if abs(region_signed_area(graph, contours) - counts[region]) > atol:
            return False
    return True


def scanline_nonzero(height: int, width: int, contours: list[list]) -> np.ndarray:
    """Fill a boolean mask with nonzero winding of closed lattice polylines."""
    hits: list[list[tuple[float, int]]] = [[] for _ in range(height)]
    for pts in contours:
        if len(pts) < 3:
            continue
        seq = pts if pts[0] == pts[-1] else list(pts) + [pts[0]]
        for (x0, y0), (x1, y1) in zip(seq, seq[1:]):
            if y0 == y1:
                continue
            for row in range(height):
                cy = row + 0.5
                upward = y0 <= cy < y1
                downward = y1 <= cy < y0
                if not (upward or downward):
                    continue
                t = (cy - y0) / (y1 - y0)
                xint = x0 + t * (x1 - x0)
                hits[row].append((xint, 1 if upward else -1))
    mask = np.zeros((height, width), dtype=np.bool_)
    for row, events in enumerate(hits):
        if not events:
            continue
        events.sort(key=lambda item: (item[0], -item[1]))
        winding = 0
        prev = 0.0
        active = False
        for xint, delta in events:
            if active and winding != 0:
                start = int(np.floor(prev + 1e-12))
                stop = int(np.ceil(xint - 1e-12) - 1)
                if stop >= start:
                    lo = max(0, start)
                    hi = min(width - 1, stop)
                    if hi >= lo:
                        mask[row, lo:hi + 1] = True
            winding += delta
            prev = xint
            active = True
    return mask


def rasterize_faces(graph: BoundaryGraph, faces: dict, height: int | None = None, width: int | None = None) -> np.ndarray:
    h = graph.height if height is None else height
    w = graph.width if width is None else width
    out = np.full((h, w), OUTSIDE, dtype=np.int32)
    for region, contours in faces.items():
        polys = [contour_points(graph, contour) for contour in contours]
        mask = scanline_nonzero(h, w, polys)
        out[mask] = region
    return out


def build_from_labels(labels: np.ndarray) -> tuple[BoundaryGraph, dict]:
    graph = extract_graph(labels)
    faces = assemble_faces(graph, labels)
    return graph, faces
