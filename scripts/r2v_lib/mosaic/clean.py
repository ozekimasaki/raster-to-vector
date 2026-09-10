"""Speckle removal on a label map that cannot erode thin strokes.

A pixel is *weak* when fewer than ``min_neighbors`` of its 8-connected
neighbors share its label. A weak pixel still survives when at least one
same-label neighbor is itself well-supported — that anchors stroke
endpoints, so lines are never shortened. Pixels that fail both tests are
reassigned to the modal neighbor label. Singletons and isolated pairs are
removed; a one-pixel-wide line (interior count 2, endpoints protected by
the interior) is untouched at ``min_neighbors=2``.
"""
from __future__ import annotations

import numpy as np

_OFFSETS = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]


def same_label_count(labels: np.ndarray) -> np.ndarray:
    """8-connected same-label neighbor count per pixel."""
    lab = np.pad(labels, 1, mode='edge')
    h, w = labels.shape
    same = np.zeros(labels.shape, dtype=np.int16)
    for dy, dx in _OFFSETS:
        same += (lab[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] == labels)
    return same


def isolated_fraction(labels: np.ndarray) -> tuple[int, float]:
    """Pixels with fewer than 2 same-label neighbors (speckle measure)."""
    same = same_label_count(labels)
    n = int((same < 2).sum())
    return n, n / max(1, labels.size)


def _weak(labels: np.ndarray, same: np.ndarray, min_neighbors: int) -> np.ndarray:
    weak = same < min_neighbors
    if not weak.any():
        return weak
    lab = np.pad(labels, 1, mode='edge')
    sup = np.pad(same, 1, mode='edge')
    h, w = labels.shape
    protected = np.zeros(labels.shape, dtype=bool)
    for dy, dx in _OFFSETS:
        vn = lab[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
        sn = sup[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
        protected |= (vn == labels) & (sn >= min_neighbors)
    return weak & ~protected


def _modal_neighbor(padded: np.ndarray, mask: np.ndarray, h: int, w: int) -> np.ndarray:
    votes = np.stack([padded[1 + dy:1 + dy + h, 1 + dx:1 + dx + w][mask] for dy, dx in _OFFSETS], axis=1)
    out = np.empty(len(votes), dtype=padded.dtype)
    for start in range(0, len(votes), 65536):
        sv = np.sort(votes[start:start + 65536], axis=1)
        counts = (sv[:, :, None] == sv[:, None, :]).sum(axis=1)
        out[start:start + len(sv)] = sv[np.arange(len(sv)), counts.argmax(axis=1)]
    return out


def despeckle_labels(labels: np.ndarray, min_neighbors: int = 2, max_passes: int = 4) -> tuple[np.ndarray, int]:
    """Reassign weak, unanchored pixels to the modal neighbor label,
    iterating to a fixpoint (bounded)."""
    if min_neighbors <= 0:
        return labels, 0
    labels = np.asarray(labels).copy()
    h, w = labels.shape
    moved = 0
    for _ in range(max_passes):
        same = same_label_count(labels)
        weak = _weak(labels, same, min_neighbors)
        n = int(weak.sum())
        if not n:
            break
        lab = np.pad(labels, 1, mode='edge')
        labels[weak] = _modal_neighbor(lab, weak, h, w)
        moved += n
    return labels, moved
