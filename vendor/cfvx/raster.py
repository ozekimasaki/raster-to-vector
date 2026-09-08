"""Input analysis, observation-model proposal, palette and region extraction.

Contour points are initialization, not the final objective (§8.1).
Palette clustering plus boundary-cluster merging approximates the
coverage observation model of a flat-color illustration with AA edges
(§6.2, §8.2): blend colors at edges are not kept as their own paints.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from skimage.measure import find_contours

from .types import ImageAnalysis, QualityContract


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_rgba(path: Path) -> tuple[np.ndarray, ImageAnalysis]:
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    im = Image.open(path).convert("RGBA")
    arr = np.array(im, dtype=np.uint8)
    h, w = arr.shape[:2]
    a = arr[:, :, 3]
    opaque = int(np.count_nonzero(a >= 250))
    trans = int(np.count_nonzero(a == 0))
    semi = h * w - opaque - trans
    unique = 0
    if opaque:
        unique = int(len(np.unique(arr[a >= 250, :3].reshape(-1, 3), axis=0)))
    notes: list[str] = []
    obs = "coverage"
    if unique > 2000:
        notes.append(
            "opaque unique colors are high; likely AA / compression, not a clean palette"
        )
        obs = "coverage_with_aa"
    if semi > 0.02 * (opaque + semi + 1):
        notes.append("silhouette has a non-trivial alpha fringe (coverage-type AA)")
    # JPEG-ish: many unique colors + few exact-alpha-255 interior flats.
    if unique > 8000:
        notes.append("compression or resampling suspected; not estimating a full codec")
        obs = "coverage_with_aa_and_possible_compression"
    notes.append("PNG does not identify the original renderer or color pipeline")
    analysis = ImageAnalysis(
        width=w,
        height=h,
        mode="RGBA",
        sha256=sha,
        opaque_pixels=opaque,
        semi_pixels=semi,
        transparent_pixels=trans,
        unique_opaque_colors=unique,
        observation_model=obs,
        observation_notes=notes,
        likely_outline=True,
    )
    return arr, analysis


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    bgr = rgb[:, :, ::-1]
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)


def _lab_to_rgb_u8(lab: np.ndarray) -> np.ndarray:
    bgr = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)
    return bgr[:, :, ::-1]


def quantize(
    rgba: np.ndarray, contract: QualityContract
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (palette RGBA Nx4, label map HxW int32 with -1 transparent, rgb mean).

    Palette colors are observed RGB means of assigned interior-ish pixels
    (geometry fixed, appearance from pixels — §12.6).
    """
    h, w, _ = rgba.shape
    rgb = rgba[:, :, :3]
    alpha = rgba[:, :, 3]
    keep = alpha >= contract.alpha_keep
    opaque = alpha >= contract.alpha_opaque
    if int(np.count_nonzero(opaque)) < 16:
        palette = np.zeros((0, 4), dtype=np.uint8)
        labels = np.full((h, w), -1, dtype=np.int32)
        return palette, labels, rgb

    lab = _rgb_to_lab(rgb)
    samples = lab[opaque].reshape(-1, 3).astype(np.float32)
    k = int(max(2, min(contract.color_count, len(samples))))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.4)
    _compact, km_labels, centers = cv2.kmeans(
        samples, k, None, criteria, 6, cv2.KMEANS_PP_CENTERS
    )
    km_labels = km_labels.ravel()
    centers, km_labels = _merge_close_centers(centers, km_labels, thresh=5.5)
    k = len(centers)

    # Assign kept pixels (including AA fringe) to nearest Lab center.
    lab_keep = lab[keep].reshape(-1, 3)
    d = _pairwise_sq(lab_keep, centers)
    assigned = np.argmin(d, axis=1).astype(np.int32)
    labels = np.full((h, w), -1, dtype=np.int32)
    labels[keep] = assigned

    labels = _drop_boundary_only_clusters(labels, k)
    labels = merge_small_components(labels, contract.min_region_area)
    labels, remap = _reindex_labels(labels)
    palette = _palette_from_labels(rgba, labels, len(remap))
    return palette, labels, rgb


def _pairwise_sq(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a2 = np.sum(a * a, axis=1, keepdims=True)
    b2 = np.sum(b * b, axis=1, keepdims=True).T
    return np.maximum(a2 + b2 - 2.0 * a @ b.T, 0.0)


def _merge_close_centers(
    centers: np.ndarray, labels: np.ndarray, thresh: float
) -> tuple[np.ndarray, np.ndarray]:
    centers = centers.astype(np.float64).copy()
    labels = labels.copy()
    while len(centers) > 4:
        d = np.sqrt(_pairwise_sq(centers, centers))
        np.fill_diagonal(d, np.inf)
        counts = np.bincount(labels, minlength=len(centers))
        for a in range(len(centers)):
            for b in range(a + 1, len(centers)):
                if min(counts[a], counts[b]) > 250 and d[a, b] > 3.5:
                    d[a, b] = d[b, a] = np.inf
        i, j = np.unravel_index(np.argmin(d), d.shape)
        if not np.isfinite(d[i, j]) or d[i, j] >= thresh:
            break
        ci = int(counts[i])
        cj = int(counts[j])
        wsum = max(ci + cj, 1)
        merged = (centers[i] * ci + centers[j] * cj) / wsum
        keep_idx = [t for t in range(len(centers)) if t != i and t != j]
        new_centers = np.vstack([centers[keep_idx], merged])
        mapping = np.empty(len(centers), dtype=np.int32)
        for new_i, old in enumerate(keep_idx):
            mapping[old] = new_i
        mapping[i] = len(keep_idx)
        mapping[j] = len(keep_idx)
        labels = mapping[labels]
        centers = new_centers
    return centers.astype(np.float32), labels


def _drop_boundary_only_clusters(labels: np.ndarray, k: int) -> np.ndarray:
    """Merge clusters that live almost only on region boundaries (AA mud)."""
    h, w = labels.shape
    out = labels.copy()
    pad = np.pad(labels, 1, mode="edge")
    for cid in range(k):
        mask = labels == cid
        area = int(np.count_nonzero(mask))
        if area == 0 or area > 0.08 * labels.size:
            continue
        ys, xs = np.where(mask)
        if len(ys) == 0:
            continue
        neigh = np.stack(
            [
                pad[ys, xs],
                pad[ys, xs + 2],
                pad[ys + 2, xs],
                pad[ys + 2, xs + 2],
                pad[ys + 1, xs],
                pad[ys + 1, xs + 2],
                pad[ys, xs + 1],
                pad[ys + 2, xs + 1],
            ],
            axis=1,
        )
        foreign = np.any((neigh != cid) & (neigh >= 0), axis=1)
        if float(np.mean(foreign)) < 0.88:
            continue
        # Majority neighbor color.
        vals = neigh[(neigh != cid) & (neigh >= 0)]
        if len(vals) == 0:
            continue
        tgt = int(np.bincount(vals.astype(np.int32)).argmax())
        out[mask] = tgt
    return out


def merge_small_components(labels: np.ndarray, min_area: int) -> np.ndarray:
    if min_area <= 1:
        return labels
    out = labels.copy()
    ids = [int(v) for v in np.unique(labels) if v >= 0]
    h, w = labels.shape
    for cid in ids:
        bin_mask = (out == cid).astype(np.uint8)
        n, cc, stats, _ = cv2.connectedComponentsWithStats(bin_mask, connectivity=8)
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area >= min_area:
                continue
            ys, xs = np.where(cc == i)
            x0 = max(int(xs.min()) - 1, 0)
            x1 = min(int(xs.max()) + 2, w)
            y0 = max(int(ys.min()) - 1, 0)
            y1 = min(int(ys.max()) + 2, h)
            roi = out[y0:y1, x0:x1]
            ring = roi[(roi >= 0) & (roi != cid)].astype(np.int32)
            if len(ring) == 0:
                out[ys, xs] = -1
            else:
                out[ys, xs] = int(np.bincount(ring).argmax())
    return out


def _reindex_labels(labels: np.ndarray) -> tuple[np.ndarray, dict[int, int]]:
    ids = [int(v) for v in np.unique(labels) if v >= 0]
    remap = {old: i for i, old in enumerate(ids)}
    out = np.full_like(labels, -1)
    for old, new in remap.items():
        out[labels == old] = new
    return out, remap


def _palette_from_labels(
    rgba: np.ndarray, labels: np.ndarray, k: int
) -> np.ndarray:
    palette = np.zeros((k, 4), dtype=np.uint8)
    rgb = rgba[:, :, :3].astype(np.float64)
    alpha = rgba[:, :, 3]
    interior = cv2.erode((labels >= 0).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1)
    for cid in range(k):
        mask = labels == cid
        core = mask & (interior.astype(bool)) & (alpha >= 250)
        use = core if np.count_nonzero(core) >= 8 else (mask & (alpha >= 200))
        if np.count_nonzero(use) == 0:
            use = mask
        pix = rgb[use] if np.count_nonzero(use) else np.array([[0.0, 0.0, 0.0]])
        mean = pix.mean(axis=0)
        luma = 0.2126 * mean[0] + 0.7152 * mean[1] + 0.0722 * mean[2]
        # Thin ink strokes mix AA gray into the mean; take a dark percentile.
        if luma < 70 and len(pix) >= 8:
            mean = np.percentile(pix, 18, axis=0)
        palette[cid, :3] = np.clip(np.round(mean), 0, 255).astype(np.uint8)
        palette[cid, 3] = 255
    return palette


def outline_label(palette: np.ndarray, labels: np.ndarray) -> int | None:
    """Darkest sufficiently large color — cartoon ink."""
    best = None
    best_luma = 1e9
    for cid, col in enumerate(palette):
        area = int(np.count_nonzero(labels == cid))
        if area < 400:
            continue
        luma = 0.2126 * col[0] + 0.7152 * col[1] + 0.0722 * col[2]
        if luma < 55 and luma < best_luma:
            best_luma = luma
            best = cid
    return best


def dilate_fills_under_outline(
    labels: np.ndarray, outline_id: int | None
) -> np.ndarray:
    """Slight fill expansion into ink so AA seams do not leak background (§13.5)."""
    if outline_id is None:
        return labels
    out = labels.copy()
    ink = labels == outline_id
    k = np.ones((3, 3), np.uint8)
    ids = [int(v) for v in np.unique(labels) if v >= 0 and v != outline_id]
    # Larger fills first so small details still win afterwards.
    ids.sort(key=lambda cid: int(np.count_nonzero(labels == cid)), reverse=True)
    for cid in ids:
        mask = (labels == cid).astype(np.uint8)
        grown = cv2.dilate(mask, k, iterations=1).astype(bool)
        take = grown & ink & (out == outline_id)
        out[take] = cid
    return out


def extract_color_contours(mask: np.ndarray) -> list[np.ndarray]:
    """Subpixel 0.5 iso-contours in SVG pixel-square coordinates (x right, y down).

    skimage treats array[i, j] as the sample at coordinate (i, j). Pixel
    (x, y) occupies [x, x+1] × [y, y+1]; the sample is at the top-left
    corner of that square. Adding 0.5 puts the iso-line on pixel centers,
    which systematically shrinks filled shapes. We therefore use (x, y) =
    (col, row) without the extra 0.5, matching the coverage convention in
    review_checks.circle_coverage after accounting for sample location.

    Empirical note: marching-squares 0.5 on a binary mask sits on the
    shared edge between 0/1 samples, i.e. the geometric boundary of the
    occupied pixel squares to within interpolation. Verification may still
    show a half-pixel bias; the report records this as estimated-contour
    reference, not latent-SVG ground truth.
    """
    if mask.dtype != bool:
        mask = mask.astype(bool)
    if not np.any(mask):
        return []
    padded = np.pad(mask.astype(np.float64), 1, mode="constant", constant_values=0.0)
    raw = find_contours(padded, 0.5)
    out: list[np.ndarray] = []
    for c in raw:
        # c is (row, col) in padded array; subtract the pad.
        xy = np.column_stack([c[:, 1] - 1.0, c[:, 0] - 1.0]).astype(np.float64)
        if len(xy) < 4:
            continue
        if not np.allclose(xy[0], xy[-1], atol=1e-8):
            xy = np.vstack([xy, xy[0]])
        # Drop zero-length runs.
        d = np.sqrt(np.sum(np.diff(xy, axis=0) ** 2, axis=1))
        keep = np.concatenate([[True], d > 1e-6])
        xy = xy[keep]
        if len(xy) < 4:
            continue
        if not np.allclose(xy[0], xy[-1], atol=1e-8):
            xy = np.vstack([xy, xy[0]])
        out.append(xy)
    return out


def point_in_ring(point: np.ndarray, ring: np.ndarray) -> bool:
    # Ray cast, even-odd.
    x, y = float(point[0]), float(point[1])
    inside = False
    n = len(ring)
    for i in range(n - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if (y1 > y) != (y2 > y):
            t = (y - y1) / (y2 - y1 + 1e-15)
            xi = x1 + t * (x2 - x1)
            if xi >= x:
                inside = not inside
    return inside
