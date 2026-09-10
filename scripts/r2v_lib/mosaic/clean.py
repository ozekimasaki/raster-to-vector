"""Speckle removal on a label map that cannot erode thin strokes.

A pixel is *weak* when fewer than ``min_neighbors`` of its 8-connected
neighbors share its label. A weak pixel still survives when at least one
same-label neighbor is itself well-supported — that anchors stroke
endpoints, so lines are never shortened. Pixels that fail both tests are
reassigned to the modal neighbor label. Singletons and isolated pairs are
removed; a one-pixel-wide line (interior count 2, endpoints protected by
the interior) is untouched at ``min_neighbors=2``.

Transparent (``OUTSIDE``) pixels are never relabeled and never vote, so a
small transparent hole inside a colored region is preserved; the price is
that a color speckle fully surrounded by transparency also survives.
"""
from __future__ import annotations

import numpy as np

from .graph import OUTSIDE

_OFFSETS = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]


def _sentinel(labels: np.ndarray) -> int:
    """A value present in no neighborhood: used to pad off-image cells."""
    if labels.size:
        if int(labels.min()) > np.iinfo(np.int64).min:
            return int(labels.min()) - 1
        if int(labels.max()) < np.iinfo(np.int64).max:
            return int(labels.max()) + 1
    return -2


def same_label_count(labels: np.ndarray) -> np.ndarray:
    """8-connected same-label neighbor count per pixel."""
    labels = np.asarray(labels, dtype=np.int64)
    lab = np.pad(labels, 1, mode='constant', constant_values=_sentinel(labels))
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
    weak = (same < min_neighbors) & (labels != OUTSIDE)
    if not weak.any():
        return weak
    lab = np.pad(labels, 1, mode='constant', constant_values=_sentinel(labels))
    sup = np.pad(same, 1, mode='constant', constant_values=0)
    h, w = labels.shape
    protected = np.zeros(labels.shape, dtype=bool)
    for dy, dx in _OFFSETS:
        vn = lab[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
        sn = sup[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
        protected |= (vn == labels) & (sn >= min_neighbors)
    return weak & ~protected


def _modal_neighbor(padded: np.ndarray, mask: np.ndarray, h: int, w: int,
                    sentinel: int, fallback: np.ndarray) -> np.ndarray:
    votes = np.stack([padded[1 + dy:1 + dy + h, 1 + dx:1 + dx + w][mask] for dy, dx in _OFFSETS], axis=1)
    out = np.empty(len(votes), dtype=padded.dtype)
    for start in range(0, len(votes), 65536):
        sv = np.sort(votes[start:start + 65536], axis=1)
        counts = (sv[:, :, None] == sv[:, None, :]).sum(axis=1)
        counts[(sv == sentinel) | (sv == OUTSIDE)] = -1
        pick = counts.argmax(axis=1)
        dead = counts[np.arange(len(sv)), pick] < 0
        picked = sv[np.arange(len(sv)), pick]
        out[start:start + len(sv)] = np.where(dead, fallback[start:start + len(sv)], picked)
    return out


def despeckle_labels(labels: np.ndarray, min_neighbors: int = 2, max_passes: int = 4) -> tuple[np.ndarray, int]:
    """Reassign weak, unanchored pixels to the modal neighbor label,
    iterating to a fixpoint (bounded). OUTSIDE cells and votes are frozen."""
    if min_neighbors <= 0:
        return labels, 0
    orig_dtype = np.asarray(labels).dtype
    labels = np.asarray(labels, dtype=np.int64).copy()
    h, w = labels.shape
    sentinel = _sentinel(labels)
    moved = 0
    for _ in range(max_passes):
        same = same_label_count(labels)
        weak = _weak(labels, same, min_neighbors)
        n = int(weak.sum())
        if not n:
            break
        lab = np.pad(labels, 1, mode='constant', constant_values=sentinel)
        labels[weak] = _modal_neighbor(lab, weak, h, w, sentinel, labels[weak])
        moved += n
    return labels.astype(orig_dtype, copy=False), moved
