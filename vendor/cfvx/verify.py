"""Independent-ish verification renderer and quality report.

Optimization/preview rasterizer: 4× box-filtered binary coverage, not
exact analytic coverage (§12.1–12.2). Geometry sample error is measured
against estimated contours, not a latent original SVG (§3, §14.1).
"""
from __future__ import annotations

import hashlib
from typing import Any

import cv2
import numpy as np

from .export import primitive_counts
from .geometry import path_to_polygon
from .types import (
    CheckStatus,
    GeometricCertificate,
    ImageAnalysis,
    QualityContract,
    QualityReport,
    Scene,
)


def rasterize_scene(scene: Scene, scale: int = 4) -> np.ndarray:
    """Return HxWx4 uint8 using painter's algorithm and 4× box coverage."""
    h, w = scene.height, scene.width
    hs, ws = h * scale, w * scale
    acc = np.zeros((hs, ws, 4), dtype=np.float32)
    for layer in scene.layers:
        color = np.array(layer.rgba, dtype=np.float32)
        mask = np.zeros((hs, ws), dtype=np.uint8)
        for path in layer.paths:
            outer = path_to_polygon(path.outer, n_per=28)
            if len(outer) < 3:
                continue
            o = np.round(outer * scale).astype(np.int32)
            cv2.fillPoly(mask, [o], 1, lineType=cv2.LINE_8)
            for hole in path.holes:
                hp = path_to_polygon(hole, n_per=20)
                if len(hp) < 3:
                    continue
                hi = np.round(hp * scale).astype(np.int32)
                cv2.fillPoly(mask, [hi], 0, lineType=cv2.LINE_8)
        if not np.any(mask):
            continue
        m = mask.astype(np.float32)[:, :, None]
        src_a = (color[3] / 255.0) * m
        src_rgb = color[None, None, :3] * src_a
        dst_a = acc[:, :, 3:4]
        dst_rgb = acc[:, :, :3]
        out_a = src_a + dst_a * (1.0 - src_a)
        out_rgb = src_rgb + dst_rgb * (1.0 - src_a)
        acc[:, :, :3] = out_rgb
        acc[:, :, 3:4] = out_a
    # Straight RGBA uint8 after downsample.
    acc_rgb = acc[:, :, :3]
    acc_a = acc[:, :, 3:4]
    # Un-premultiply for storage; empty stays 0.
    straight = np.zeros((hs, ws, 4), dtype=np.float32)
    nz = acc_a[:, :, 0] > 1e-6
    straight[nz, :3] = acc_rgb[nz] / np.clip(acc_a[nz, 0:1], 1e-6, None)
    straight[:, :, 3:4] = acc_a * 255.0
    straight[:, :, :3] = np.clip(straight[:, :, :3], 0, 255)
    u8 = np.round(straight).astype(np.uint8)
    if scale == 1:
        return u8
    return cv2.resize(u8, (w, h), interpolation=cv2.INTER_AREA)


def _metrics(original: np.ndarray, recon: np.ndarray) -> dict[str, Any]:
    o = original.astype(np.float32)
    r = recon.astype(np.float32)
    # Premultiplied RMSE — transparent RGB is not free-floating (§6.3).
    oa = o[:, :, 3:4] / 255.0
    ra = r[:, :, 3:4] / 255.0
    op = o[:, :, :3] * oa
    rp = r[:, :, :3] * ra
    premul = np.concatenate([op, o[:, :, 3:4]], axis=2)
    rpre = np.concatenate([rp, r[:, :, 3:4]], axis=2)
    diff = premul - rpre
    mse = float(np.mean(diff * diff))
    rmse = float(np.sqrt(mse))
    mae = float(np.mean(np.abs(diff)))
    sil_o = o[:, :, 3] > 32
    sil_r = r[:, :, 3] > 32
    inter = float(np.count_nonzero(sil_o & sil_r))
    union = float(np.count_nonzero(sil_o | sil_r)) or 1.0
    iou = inter / union
    # Interior color error (both strongly opaque).
    core = (o[:, :, 3] >= 250) & (r[:, :, 3] >= 250)
    if np.count_nonzero(core):
        interior_rmse = float(
            np.sqrt(np.mean((o[core, :3] - r[core, :3]) ** 2))
        )
    else:
        interior_rmse = None
    return {
        "premultiplied_rmse": rmse,
        "premultiplied_mae": mae,
        "silhouette_iou": iou,
        "interior_rgb_rmse": interior_rmse,
        "renderer": "cv2.fillPoly + 4x box-filter downsample",
        "renderer_kind": "optimization_preview_not_exact_coverage",
    }


def sample_geometry_error(scene: Scene, original_contours: list[np.ndarray]) -> float | None:
    """Max distance from estimated-contour samples to reconstructed path.

    This is NOT a continuous Hausdorff certificate (§14).
    """
    if not original_contours:
        return None
    polys: list[np.ndarray] = []
    for layer in scene.layers:
        for path in layer.paths:
            polys.append(path_to_polygon(path.outer, n_per=12))
            for hole in path.holes:
                polys.append(path_to_polygon(hole, n_per=10))
    if not polys:
        return None
    verts = np.vstack(polys)
    max_d = 0.0
    rng = np.random.default_rng(20260908)
    for c in original_contours:
        if len(c) == 0:
            continue
        if len(c) > 120:
            idx = rng.choice(len(c), 120, replace=False)
            pts = c[idx]
        else:
            pts = c
        # Distance to polyline vertices is a sample, not a continuous bound.
        # Dense sampling (see sample_segment) keeps this close to the curve.
        d2 = np.sum((pts[:, None, :] - verts[None, :, :]) ** 2, axis=2)
        max_d = max(max_d, float(np.sqrt(d2.min(axis=1).max())))
    return max_d


def build_report(
    scene: Scene,
    analysis: ImageAnalysis,
    contract: QualityContract,
    original: np.ndarray,
    recon: np.ndarray,
    svg_bytes: bytes,
    warnings: list[str],
    extra_provenance: dict,
    contour_sample_error: float | None,
) -> QualityReport:
    metrics = _metrics(original, recon)
    geom_status: CheckStatus = "indeterminate"
    if contour_sample_error is None:
        geom_status = "indeterminate"
    elif contour_sample_error <= contract.source_pixel_tolerance:
        geom_status = "passed"
    else:
        geom_status = "failed"

    iou = metrics["silhouette_iou"]
    interior = metrics["interior_rgb_rmse"]
    native: CheckStatus = "indeterminate"
    if iou >= 0.985 and (interior is None or interior <= 18.0):
        native = "passed"
    elif iou >= 0.95:
        native = "failed"
        warnings.append(
            "preview-renderer fidelity is below the internal pass bar; "
            "browser rendering is still required"
        )
    else:
        native = "failed"

    # Overall: we never claim latent-SVG recovery.
    overall: str
    if contract.strict_vector_only and b"<image" in svg_bytes:
        overall = "failed"
        warnings.append("strict vector contract violated: embedded raster")
    elif native == "passed" and geom_status in ("passed", "indeterminate"):
        overall = "passed"
    elif native == "failed" and iou < 0.9:
        overall = "failed"
    else:
        overall = "partial"

    warnings = list(warnings)
    warnings.append(
        "geometry certificate uses estimated contours / preview raster, "
        "not a lost original SVG"
    )
    warnings.append(
        "continuous Hausdorff upper bound was not computed (indeterminate)"
    )

    cert = GeometricCertificate(
        status="indeterminate" if contour_sample_error is None else geom_status,
        reference_kind="estimated_contour",
        units="source_pixel",
        requested_tolerance=contract.source_pixel_tolerance,
        sample_max_error=contour_sample_error,
        verified_upper_bound=None,
        numeric_method="sampled nearest-vertex distance; not a branch-and-bound bound",
    )

    counts = primitive_counts(scene)
    n_paths = sum(len(l.paths) for l in scene.layers)
    n_seg = sum(counts.values())
    return QualityReport(
        overall=overall,  # type: ignore[arg-type]
        contract={
            "mode": contract.mode,
            "strict_vector_only": contract.strict_vector_only,
            "source_pixel_tolerance": contract.source_pixel_tolerance,
            "color_count": contract.color_count,
            "min_region_area": contract.min_region_area,
        },
        analysis={
            "width": analysis.width,
            "height": analysis.height,
            "sha256": analysis.sha256,
            "opaque_pixels": analysis.opaque_pixels,
            "semi_pixels": analysis.semi_pixels,
            "unique_opaque_colors": analysis.unique_opaque_colors,
            "observation_model": analysis.observation_model,
            "observation_notes": analysis.observation_notes,
        },
        palette=[list(map(int, layer.rgba)) for layer in scene.layers],
        geometry=cert,
        topology="indeterminate",
        native_rendering=native,
        latent_geometry_ground_truth_available=False,
        primitive_counts=counts,
        layer_count=len(scene.layers),
        path_count=n_paths,
        segment_count=n_seg,
        raster_metrics=metrics,
        warnings=warnings,
        provenance={
            "engine": "cfvx",
            "engine_version": "0.1.0",
            "seed": 20260908,
            **extra_provenance,
        },
        svg_hash=hashlib.sha256(svg_bytes).hexdigest(),
    )


def side_by_side(original: np.ndarray, recon: np.ndarray) -> np.ndarray:
    """Original | reconstruction | amplified difference."""
    h, w = original.shape[:2]
    diff = np.abs(original.astype(np.int16) - recon.astype(np.int16)).clip(0, 255).astype(np.uint8)
    amp = np.clip(diff.astype(np.int32) * 4, 0, 255).astype(np.uint8)
    amp[:, :, 3] = 255
    left = original.copy()
    mid = recon.copy()
    # Composite on white for viewing.
    def on_white(a: np.ndarray) -> np.ndarray:
        rgb = a[:, :, :3].astype(np.float32)
        al = a[:, :, 3:4].astype(np.float32) / 255.0
        out = rgb * al + 255.0 * (1.0 - al)
        u = np.round(out).astype(np.uint8)
        return np.concatenate([u, np.full((h, w, 1), 255, np.uint8)], axis=2)

    gap = np.full((h, 8, 4), 240, dtype=np.uint8)
    gap[:, :, 3] = 255
    return np.concatenate([on_white(left), gap, on_white(mid), gap, on_white(amp)], axis=1)
