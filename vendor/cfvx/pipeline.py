"""CFV-X vectorize pipeline (review §16.1, reduced to a runnable subset).

Implemented:
  input hash / analysis → observation hypothesis → region proposals →
  contour initialization → line/arc/cubic selection → SVG serialize →
  preview-renderer verification.

Not implemented as certified solvers (reported, not faked):
  joint geometric relations, exact coverage inverse-render, branch-and-bound
  Hausdorff bounds, independent SVG DOM re-parse geometry certificate.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .export import primitive_counts, scene_to_svg
from .geometry import (
    contour_as_polyline,
    fit_contour,
    path_to_polygon,
    polygon_area,
    reverse_segments,
)
from .raster import (
    dilate_fills_under_outline,
    extract_color_contours,
    load_rgba,
    outline_label,
    point_in_ring,
    quantize,
)
from .types import (
    ColorLayer,
    CompoundPath,
    QualityContract,
    Scene,
)
from .verify import build_report, rasterize_scene, sample_geometry_error, side_by_side


def _local_eps(area: float, base: float) -> float:
    a = abs(area)
    if a < 80:
        return min(base, 0.38)
    if a < 400:
        return min(base, 0.52)
    return base


def _nests(inner: np.ndarray, outer: np.ndarray) -> bool:
    if abs(polygon_area(inner)) >= abs(polygon_area(outer)) - 1e-6:
        return False
    test = inner[len(inner) // 3]
    return point_in_ring(test, outer)


def _compounds_from_mask(mask: np.ndarray, eps: float) -> tuple[list[CompoundPath], list[np.ndarray], float]:
    n, cc = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    paths: list[CompoundPath] = []
    all_contours: list[np.ndarray] = []
    max_err = 0.0
    for i in range(1, n):
        sub = cc == i
        area_px = int(np.count_nonzero(sub))
        contours = extract_color_contours(sub)
        if not contours:
            continue
        all_contours.extend(contours)
        fitted: list[tuple[np.ndarray, list, float]] = []
        local = _local_eps(float(area_px), eps)
        for c in contours:
            if abs(polygon_area(c)) < 2.5:
                continue
            segs, err = fit_contour(c, local, closed=True)
            max_err = max(max_err, err)
            if segs:
                fitted.append((c, segs, err))
        if not fitted:
            continue
        fitted.sort(key=lambda t: abs(polygon_area(t[0])), reverse=True)
        nfit = len(fitted)
        parent = [None] * nfit
        for i in range(nfit):
            for j in range(i):
                if _nests(fitted[i][0], fitted[j][0]):
                    parent[i] = j  # last (smallest) containing contour

        def depth(i: int) -> int:
            d, p = 0, parent[i]
            seen = 0
            while p is not None and seen < nfit:
                d += 1
                p = parent[p]
                seen += 1
            return d

        for i, (oring, osegs, _) in enumerate(fitted):
            if depth(i) % 2 != 0:
                continue
            holes: list[list] = []
            for k in range(nfit):
                if parent[k] == i and depth(k) % 2 == 1:
                    hsegs = fitted[k][1]
                    if polygon_area(fitted[k][0]) * polygon_area(oring) > 0:
                        hsegs = reverse_segments(hsegs)
                    holes.append(hsegs)
            outer_a = abs(polygon_area(path_to_polygon(osegs)))
            hole_a = sum(abs(polygon_area(path_to_polygon(h))) for h in holes)
            net = max(outer_a - hole_a, 0.0)
            # Fitted primitives can self-intersect on thin necks; evenodd/nonzero
            # then drops a lobe. Fall back to a contour polyline (§5.3 fidelity first).
            if abs(net - area_px) > 0.18 * max(area_px, 1.0) + 25.0:
                osegs = contour_as_polyline(oring, local)
                holes = []
                for k in range(nfit):
                    if parent[k] == i and depth(k) % 2 == 1:
                        h = contour_as_polyline(fitted[k][0], local)
                        if polygon_area(fitted[k][0]) * polygon_area(oring) > 0:
                            h = reverse_segments(h)
                        holes.append(h)
            paths.append(
                CompoundPath(
                    outer=osegs,
                    holes=holes,
                    area=float(abs(polygon_area(oring))),
                )
            )
    return paths, all_contours, max_err


def build_scene(
    rgba: np.ndarray,
    palette: np.ndarray,
    labels: np.ndarray,
    contract: QualityContract,
) -> tuple[Scene, list[np.ndarray], float]:
    h, w = labels.shape
    ink = outline_label(palette, labels)
    paint_labels = dilate_fills_under_outline(labels, ink)
    ids = [int(v) for v in np.unique(labels) if v >= 0]
    ids.sort(key=lambda cid: int(np.count_nonzero(labels == cid)), reverse=True)
    if ink is not None and ink in ids:
        ids = [c for c in ids if c != ink] + [ink]

    layers: list[ColorLayer] = []
    contours: list[np.ndarray] = []
    max_err = 0.0
    for cid in ids:
        if cid == ink:
            mask = labels == cid
        else:
            mask = paint_labels == cid
        paths, cs, err = _compounds_from_mask(mask, contract.source_pixel_tolerance)
        max_err = max(max_err, err)
        contours.extend(cs)
        rgba_c = tuple(int(x) for x in palette[cid])
        layers.append(
            ColorLayer(
                rgba=rgba_c,  # type: ignore[arg-type]
                paths=paths,
                pixel_count=int(np.count_nonzero(labels == cid)),
                origin="observed",
                is_outline=(cid == ink),
            )
        )
    scene = Scene(width=w, height=h, layers=layers, view_box=(0.0, 0.0, float(w), float(h)))
    return scene, contours, max_err


def vectorize(
    input_path: str | Path,
    output_svg: str | Path | None = None,
    contract: QualityContract | None = None,
    write_preview: bool = True,
    write_report: bool = True,
) -> dict:
    t0 = time.perf_counter()
    input_path = Path(input_path)
    contract = contract or QualityContract()
    rgba, analysis = load_rgba(input_path)
    palette, labels, _rgb = quantize(rgba, contract)
    if len(palette) == 0:
        raise RuntimeError("no opaque content to vectorize")

    scene, contours, fit_err = build_scene(rgba, palette, labels, contract)
    title = input_path.stem
    svg = scene_to_svg(scene, title=title)
    svg_bytes = svg.encode("utf-8")

    recon = rasterize_scene(scene, scale=4)
    warnings: list[str] = []
    if fit_err > contract.source_pixel_tolerance:
        warnings.append(
            f"some spans used polyline fallback; sample contour fit err={fit_err:.3f}px"
        )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if elapsed_ms > contract.time_budget_ms:
        warnings.append("time budget exceeded; result is whatever was completed")

    sample_err = sample_geometry_error(scene, contours)
    report = build_report(
        scene,
        analysis,
        contract,
        rgba,
        recon,
        svg_bytes,
        warnings,
        extra_provenance={
            "elapsed_ms": round(elapsed_ms, 1),
            "palette_size": int(len(palette)),
            "contour_fit_max_error_px": fit_err,
            "input_name": input_path.name,
        },
        contour_sample_error=sample_err,
    )

    if output_svg is None:
        output_svg = input_path.with_suffix(".cfvx.svg")
    output_svg = Path(output_svg)
    output_svg.parent.mkdir(parents=True, exist_ok=True)
    output_svg.write_text(svg, encoding="utf-8")

    report_path = None
    preview_path = None
    quant_path = None
    if write_report:
        report_path = output_svg.with_suffix(".report.json")
        report_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    if write_preview:
        preview_path = output_svg.with_suffix(".preview.png")
        Image.fromarray(side_by_side(rgba, recon), "RGBA").save(preview_path)
        # Quantized view for debugging palette.
        quant_path = output_svg.with_suffix(".quant.png")
        qimg = np.zeros_like(rgba)
        for cid, col in enumerate(palette):
            qimg[labels == cid] = col
        Image.fromarray(qimg, "RGBA").save(quant_path)

    sidecar = {
        "contract": asdict(contract),
        "primitive_counts": primitive_counts(scene),
        "layers": [
            {
                "rgba": list(layer.rgba),
                "path_count": len(layer.paths),
                "pixel_count": layer.pixel_count,
                "is_outline": layer.is_outline,
                "origin": layer.origin,
            }
            for layer in scene.layers
        ],
    }
    sidecar_path = output_svg.with_suffix(".sidecar.json")
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    return {
        "svg_path": str(output_svg),
        "report_path": str(report_path) if report_path else None,
        "preview_path": str(preview_path) if preview_path else None,
        "quant_path": str(quant_path) if quant_path else None,
        "sidecar_path": str(sidecar_path),
        "report": report.to_dict(),
        "elapsed_ms": elapsed_ms,
    }


def synthesize_circle_png(path: Path, size: int = 48, cx: float = 24.2, cy: float = 23.7, r: float = 14.5) -> None:
    """Box-coverage circle used by selftest. Matched forward model (§18.3 caution)."""
    yy, xx = np.mgrid[:size, :size]
    # 4x coverage then downsample.
    s = 4
    y2, x2 = np.mgrid[: size * s, : size * s]
    dist = np.sqrt((x2 / s + 0.5 / s - cx) ** 2 + (y2 / s + 0.5 / s - cy) ** 2)
    cov = (dist <= r).astype(np.float32)
    cov = cv2.resize(cov, (size, size), interpolation=cv2.INTER_AREA)
    img = np.zeros((size, size, 4), dtype=np.uint8)
    img[:, :, 0] = 30
    img[:, :, 1] = 90
    img[:, :, 2] = 220
    img[:, :, 3] = np.clip(np.round(cov * 255), 0, 255).astype(np.uint8)
    Image.fromarray(img, "RGBA").save(path)
