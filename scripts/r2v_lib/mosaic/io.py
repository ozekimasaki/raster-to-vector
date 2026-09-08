"""Load labels, paint colors, and write mosaic-draft artifacts."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from ..images import load_image, propose, save_json
from .compose import compose_svg, reversal_pairs_match, shared_boundary_json
from .faces import area_matches_pixels, build_from_labels, rasterize_faces
from .fit import DEFAULT_TAU, fit_graph
from .graph import OUTSIDE


def palette_from_image(rgba: np.ndarray, labels: np.ndarray) -> dict[int, tuple]:
    paints = {}
    ids = np.unique(labels)
    for rid in ids:
        rid = int(rid)
        if rid == OUTSIDE:
            continue
        mask = labels == rid
        if not np.any(mask):
            continue
        mean = rgba[mask].mean(axis=0)
        paints[rid] = (
            int(round(mean[0])),
            int(round(mean[1])),
            int(round(mean[2])),
            int(round(mean[3])),
        )
    return paints


def palette_from_propose(meta: dict) -> dict[int, tuple]:
    paints = {}
    for i, rgb in enumerate(meta.get('palette_rgb') or []):
        paints[i] = (int(rgb[0]), int(rgb[1]), int(rgb[2]), 255)
    return paints


def load_labels(path) -> np.ndarray:
    labels = np.load(path, allow_pickle=False)
    if labels.ndim != 2:
        raise ValueError('labels.npy must be a 2-D integer map')
    return labels.astype(np.int32, copy=False)


def mosaic_draft(
    source,
    out,
    colors: int = 22,
    from_labels=None,
    mode: str = 'polygon',
    frame: int | None = None,
    tolerance: float = DEFAULT_TAU,
) -> dict:
    if mode not in ('pixel', 'polygon', 'curve'):
        raise ValueError('mode must be pixel, polygon, or curve')
    if not 2 <= int(colors) <= 256:
        raise ValueError('--colors must be 2..256')
    if not 0 < float(tolerance) <= 10:
        raise ValueError('--tolerance must be in (0, 10]')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    im, meta = load_image(source, frame)
    rgba = np.asarray(im)
    generated_labels = False
    if from_labels is not None:
        labels = load_labels(from_labels)
        if labels.shape != rgba.shape[:2]:
            raise ValueError(
                f'Label map {labels.shape} does not match image {(rgba.shape[0], rgba.shape[1])}'
            )
        paints = palette_from_image(rgba, labels)
        palette_path = Path(from_labels).resolve().parent / 'palette.json'
        if palette_path.is_file():
            import json
            extra = json.loads(palette_path.read_text(encoding='utf-8'))
            proposed = palette_from_propose(extra)
            if proposed:
                paints.update(proposed)
                for rid, rgb in list(paints.items()):
                    if rid in proposed and len(rgb) > 3:
                        paints[rid] = (*proposed[rid][:3], rgb[3])
    else:
        propose_meta = propose(source, out, int(colors), frame)
        labels = load_labels(out / 'labels.npy')
        paints = palette_from_propose(propose_meta)
        for rid, rgba_mean in palette_from_image(rgba, labels).items():
            if rid in paints:
                paints[rid] = (*paints[rid][:3], rgba_mean[3])
            else:
                paints[rid] = rgba_mean
        generated_labels = True
        meta = propose_meta

    graph, faces = build_from_labels(labels)
    fitted = fit_graph(graph, mode, float(tolerance))
    curve_fallback = mode == 'curve' and any(item.backend != 'curve' for item in fitted)
    svg = compose_svg(graph, faces, fitted, paints, title=Path(source).stem)
    (out / 'candidate.svg').write_text(svg, encoding='utf-8')
    payload = shared_boundary_json(graph, faces, fitted, paints)
    save_json(out / 'shared-boundary.json', payload)

    areas_ok = area_matches_pixels(graph, faces, labels)
    coords_ok = reversal_pairs_match(graph, faces, fitted)
    round_trip = False
    round_trip_checked = False
    if mode == 'pixel':
        recon = rasterize_faces(graph, faces)
        round_trip = bool(np.array_equal(recon, labels.astype(np.int32, copy=False)))
        round_trip_checked = True
        Image.fromarray(np.uint8(np.clip(recon + 1, 0, 255))).save(out / 'mosaic-recon.png')

    limitations = [
        'Draft only; not a WVR/CFV-X certificate',
        'Geometric partition does not remove renderer AA hairlines',
        '4-neighborhood crack boundaries; diagonal contact is pinched at a node',
        'Small regions are not removed by area',
    ]
    if curve_fallback:
        limitations.append('curve mode fell back to polygon on one or more segments (CFV-X unavailable or error budget)')

    result = {
        'status': 'draft_only',
        'source': meta,
        'candidate_exists': True,
        'mode': mode if not curve_fallback else 'polygon',
        'requested_mode': mode,
        'tolerance': float(tolerance),
        'width': graph.width,
        'height': graph.height,
        'node_count': len(graph.nodes),
        'segment_count': len(graph.segments),
        'face_count': len(faces),
        'generated_labels': generated_labels,
        'area_matches_pixels': areas_ok,
        'shared_coordinates_consistent': coords_ok,
        'pixel_round_trip': round_trip if round_trip_checked else None,
        'quality_status': 'indeterminate',
        'limitations': limitations,
    }
    save_json(out / 'draft-status.json', result)
    return result
