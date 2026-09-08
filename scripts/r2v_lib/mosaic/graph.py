"""Integer crack-boundary graph on the pixel-corner lattice.

Pixel (x, y) occupies the unit square (x, y)..(x+1, y+1). All boundary
geometry lives on corners 0..W × 0..H. OUTSIDE is a real label so image
borders use the same rules as interior junctions.

This is a label-map tessellation, not a general DCEL or arrangement.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

OUTSIDE = -1
N, E, S, W = 0, 1, 2, 3
DELTA = ((0, -1), (1, 0), (0, 1), (-1, 0))


def opposite(direction: int) -> int:
    return (direction + 2) % 4


def turn_right(direction: int) -> int:
    return (direction + 1) % 4


def turn_left(direction: int) -> int:
    return (direction + 3) % 4


@dataclass
class SegRef:
    seg: int
    forward: bool


@dataclass
class Node:
    x: int
    y: int
    out: list = field(default_factory=lambda: [None, None, None, None])


@dataclass
class Segment:
    points: list
    start: int | None
    end: int | None
    left: int
    right: int
    start_dir: int
    end_dir: int

    @property
    def is_ring(self) -> bool:
        return self.start is None and self.end is None


@dataclass
class BoundaryGraph:
    width: int
    height: int
    nodes: list
    segments: list
    masks: np.ndarray
    node_at: np.ndarray


def pixel_label(labels: np.ndarray, px: int, py: int) -> int:
    h, w = labels.shape
    if px < 0 or py < 0 or px >= w or py >= h:
        return OUTSIDE
    return int(labels[py, px])


def left_pixel(labels: np.ndarray, cx: int, cy: int, direction: int) -> int:
    if direction == E:
        return pixel_label(labels, cx, cy - 1)
    if direction == S:
        return pixel_label(labels, cx, cy)
    if direction == W:
        return pixel_label(labels, cx - 1, cy)
    return pixel_label(labels, cx - 1, cy - 1)


def right_pixel(labels: np.ndarray, cx: int, cy: int, direction: int) -> int:
    if direction == E:
        return pixel_label(labels, cx, cy)
    if direction == S:
        return pixel_label(labels, cx - 1, cy)
    if direction == W:
        return pixel_label(labels, cx - 1, cy - 1)
    return pixel_label(labels, cx, cy - 1)


def corner_mask(labels: np.ndarray, cx: int, cy: int) -> int:
    nw = pixel_label(labels, cx - 1, cy - 1)
    ne = pixel_label(labels, cx, cy - 1)
    sw = pixel_label(labels, cx - 1, cy)
    se = pixel_label(labels, cx, cy)
    mask = 0
    if nw != ne:
        mask |= 1 << N
    if ne != se:
        mask |= 1 << E
    if sw != se:
        mask |= 1 << S
    if nw != sw:
        mask |= 1 << W
    return mask


def _popcount(mask: int) -> int:
    return (mask & 1) + ((mask >> 1) & 1) + ((mask >> 2) & 1) + ((mask >> 3) & 1)


def step(cx: int, cy: int, direction: int) -> tuple[int, int]:
    dx, dy = DELTA[direction]
    return cx + dx, cy + dy


def extract_graph(labels: np.ndarray) -> BoundaryGraph:
    labels = np.asarray(labels)
    if labels.ndim != 2:
        raise ValueError('Label map must be a 2-D array')
    h, w = (int(labels.shape[0]), int(labels.shape[1]))
    if h < 1 or w < 1:
        raise ValueError('Label map must be at least 1x1')
    masks = np.zeros((h + 1, w + 1), dtype=np.uint8)
    node_at = np.full((h + 1, w + 1), -1, dtype=np.int32)
    nodes: list[Node] = []
    for cy in range(h + 1):
        for cx in range(w + 1):
            mask = corner_mask(labels, cx, cy)
            masks[cy, cx] = mask
            if _popcount(mask) >= 3:
                node_at[cy, cx] = len(nodes)
                nodes.append(Node(x=cx, y=cy))

    horiz = np.zeros((h + 1, w), dtype=np.bool_)
    vert = np.zeros((h, w + 1), dtype=np.bool_)

    def visited(cx: int, cy: int, direction: int) -> bool:
        if direction == E:
            return bool(horiz[cy, cx])
        if direction == W:
            return bool(horiz[cy, cx - 1])
        if direction == S:
            return bool(vert[cy, cx])
        return bool(vert[cy - 1, cx])

    def mark(cx: int, cy: int, direction: int) -> None:
        if direction == E:
            horiz[cy, cx] = True
        elif direction == W:
            horiz[cy, cx - 1] = True
        elif direction == S:
            vert[cy, cx] = True
        else:
            vert[cy - 1, cx] = True

    def present(cx: int, cy: int, direction: int) -> bool:
        return bool(masks[cy, cx] & (1 << direction))

    limit = (w + h + 2) * 8 + 16

    def walk(sx: int, sy: int, sd: int, *, stop_nodes: bool) -> tuple[list, int, int, int]:
        points = [(sx, sy)]
        cx, cy, direction = sx, sy, sd
        left = left_pixel(labels, cx, cy, direction)
        right = right_pixel(labels, cx, cy, direction)
        end_dir = direction
        while True:
            if not present(cx, cy, direction):
                raise RuntimeError(f'Missing edge at {(cx, cy)} dir={direction}')
            mark(cx, cy, direction)
            cx, cy = step(cx, cy, direction)
            points.append((cx, cy))
            end_dir = direction
            if len(points) > limit:
                raise RuntimeError('Boundary walk exceeded lattice size')
            if stop_nodes and int(node_at[cy, cx]) >= 0:
                break
            if not stop_nodes and (cx, cy) == (sx, sy):
                break
            arrived = direction
            used = opposite(arrived)
            others = [d for d in range(4) if present(cx, cy, d) and d != used]
            if len(others) != 1:
                raise RuntimeError(f'Expected a unique continuation at {(cx, cy)}, got {others}')
            direction = others[0]
        return points, left, right, end_dir

    segments: list[Segment] = []

    def register(seg_id: int, seg: Segment) -> None:
        if seg.start is not None:
            nodes[seg.start].out[seg.start_dir] = SegRef(seg_id, True)
        if seg.end is not None:
            nodes[seg.end].out[opposite(seg.end_dir)] = SegRef(seg_id, False)

    for node_id, node in enumerate(nodes):
        for direction in range(4):
            if not present(node.x, node.y, direction) or visited(node.x, node.y, direction):
                continue
            points, left, right, end_dir = walk(node.x, node.y, direction, stop_nodes=True)
            end_id = int(node_at[points[-1][1], points[-1][0]])
            if end_id < 0:
                raise RuntimeError('Node-to-node walk did not land on a node')
            seg = Segment(
                points=points,
                start=node_id,
                end=end_id,
                left=left,
                right=right,
                start_dir=direction,
                end_dir=end_dir,
            )
            register(len(segments), seg)
            segments.append(seg)

    for cy in range(h + 1):
        for cx in range(w + 1):
            for direction in (E, S):
                if direction == E and cx >= w:
                    continue
                if direction == S and cy >= h:
                    continue
                if not present(cx, cy, direction) or visited(cx, cy, direction):
                    continue
                points, left, right, end_dir = walk(cx, cy, direction, stop_nodes=False)
                seg = Segment(
                    points=points,
                    start=None,
                    end=None,
                    left=left,
                    right=right,
                    start_dir=direction,
                    end_dir=end_dir,
                )
                segments.append(seg)

    return BoundaryGraph(
        width=w,
        height=h,
        nodes=nodes,
        segments=segments,
        masks=masks,
        node_at=node_at,
    )


def successor_dir(graph: BoundaryGraph, labels: np.ndarray, cx: int, cy: int, d_in: int, region: int) -> int:
    mask = int(graph.masks[cy, cx])
    for direction in (turn_right(d_in), d_in, turn_left(d_in)):
        if mask & (1 << direction) and left_pixel(labels, cx, cy, direction) == region:
            return direction
    raise RuntimeError(f'No successor at {(cx, cy)} for region {region} arriving {d_in}')


def shoelace(points: list) -> float:
    if len(points) < 3:
        return 0.0
    pts = points[:-1] if points[0] == points[-1] else points
    acc = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        acc += x0 * y1 - x1 * y0
    return 0.5 * acc


def contour_points(graph: BoundaryGraph, contour: list) -> list:
    pts: list = []
    for i, ref in enumerate(contour):
        seq = graph.segments[ref.seg].points
        if not ref.forward:
            seq = list(reversed(seq))
        if i == 0:
            pts.extend(seq)
        else:
            pts.extend(seq[1:])
    return pts
