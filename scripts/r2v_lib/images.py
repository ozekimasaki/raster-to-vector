from __future__ import annotations

import hashlib
import io
import json
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps

MAX_PIXELS = 25_000_000


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def load_image(path, frame=None):
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(path) as raw:
            if raw.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValueError('Supported inputs: PNG, JPEG, WebP')
            if raw.width * raw.height > MAX_PIXELS:
                raise ValueError('Input exceeds 25 million pixels; explicitly prepare a working copy')
            frames = getattr(raw, 'n_frames', 1)
            if frames > 1 and frame is None:
                raise ValueError('Animated/multiframe input requires explicit --frame')
            selected = frame if frame is not None else 0
            if not 0 <= selected < frames:
                raise ValueError('Frame index out of range')
            raw.seek(selected)
            orientation = raw.getexif().get(274, 1)
            icc = raw.info.get('icc_profile')
            im = ImageOps.exif_transpose(raw).copy()
            alpha = im.convert('RGBA').getchannel('A')
            color_note = 'assumed_sRGB_no_ICC'
            if icc:
                # Preserve source color mode for CMYK/gray profiles; alpha is handled separately.
                mode = im.mode if im.mode in ('RGB', 'CMYK', 'L', 'LAB') else 'RGB'
                try:
                    im = ImageCms.profileToProfile(im.convert(mode), ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                                  ImageCms.createProfile('sRGB'), outputMode='RGB')
                except Exception as exc:
                    raise ValueError(f'ICC conversion failed: {exc}') from exc
                color_note = 'ICC_converted_to_sRGB'
            im = im.convert('RGBA')
            im.putalpha(alpha)
    return im, {'sha256': digest(path), 'width': im.width, 'height': im.height,
                'frame': selected, 'frame_count': frames, 'exif_orientation': orientation,
                'color_management': color_note, 'working_color_space': 'encoded_sRGB',
                'icc_sha256': hashlib.sha256(icc).hexdigest() if icc else None}


def analyze(path, out, frame=None):
    im, meta = load_image(path, frame)
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(im)
    a = arr[:, :, 3]
    sample = im.copy(); sample.thumbnail((512, 512))
    s = np.asarray(sample)
    visible = s[:, :, 3] > 0
    colors = np.unique(s[:, :, :3][visible], axis=0).shape[0]
    # Premultiplied luminance edges, measured on the reported thumbnail only.
    lum = (s[:, :, :3].astype(float) @ np.array([.2126, .7152, .0722])) / 255
    lum *= s[:, :, 3] / 255
    dx = np.abs(np.diff(lum, axis=1)); dy = np.abs(np.diff(lum, axis=0))
    meta.update(alpha={'zero': int((a == 0).sum()), 'partial': int(((a > 0) & (a < 255)).sum()),
                       'opaque': int((a == 255).sum()), 'histogram': np.bincount(a.ravel(), minlength=256).tolist()},
                sampled_unique_visible_rgb=int(colors), statistics_sample_size=list(sample.size),
                edge_mean=float((dx.sum() + dy.sum()) / max(1, dx.size + dy.size)),
                classification='indeterminate', notes=['Statistics do not establish photo/AA/compression/material alpha'])
    im.save(out / 'normalized.png')
    sample.save(out / 'thumbnail.png')
    im.getchannel('A').save(out / 'alpha.png')
    save_json(out / 'analysis.json', meta)
    return meta


def _median_cut_palette(sampled, n_colors):
    if len(sampled) <= n_colors:
        return np.unique(sampled, axis=0)
    quant = Image.fromarray(sampled.reshape(1, -1, 3)).quantize(colors=n_colors, method=Image.Quantize.MEDIANCUT,
                                                              dither=Image.Dither.NONE)
    palette = np.array(quant.getpalette(), dtype=np.uint8).reshape(-1, 3)
    return palette[np.unique(np.asarray(quant))]


SATURATION_STRATUM_MIN = 48


def propose(path, out, colors, frame=None):
    if not 2 <= colors <= 256:
        raise ValueError('--colors must be 2..256')
    im, meta = load_image(path, frame)
    arr = np.asarray(im); alpha = arr[:, :, 3]
    pixels = arr[:, :, :3][alpha > 0]
    labels = np.full(alpha.shape, -1, dtype=np.int16)
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    if pixels.size:
        # Deterministic subsample; hidden RGB is excluded and alpha never quantized.
        stride = max(1, int(np.ceil(len(pixels) / 250000)))
        sampled = pixels[::stride]
        # Volume-proportional median cut lets a dominant flat background absorb
        # most palette slots; a small saturated stratum gets a floor share so
        # rare accent colors survive.
        quantizer = 'median_cut'
        sat = sampled.astype(np.int16).max(axis=1) - sampled.min(axis=1)
        vivid = sat >= SATURATION_STRATUM_MIN
        if colors >= 8 and int(vivid.sum()) >= 64 and int((~vivid).sum()) >= 64:
            n_vivid = max(4, min(colors - 4, int(np.ceil(colors * 0.35))))
            palette = np.vstack([_median_cut_palette(sampled[vivid], n_vivid),
                                 _median_cut_palette(sampled[~vivid], colors - n_vivid)])
            quantizer = 'stratified_saturation'
        else:
            palette = _median_cut_palette(sampled, colors)
        # Explicit nearest RGB mapping, chunked to avoid H*W*K allocation.
        idx = np.empty(len(pixels), dtype=np.int16)
        p = palette.astype(np.float32)
        for start in range(0, len(pixels), 4096):
            v = pixels[start:start + 4096].astype(np.float32)
            idx[start:start + len(v)] = ((v[:, None, :] - p[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
        labels[alpha > 0] = idx
        result = np.zeros_like(arr); result[:, :, 3] = alpha
        result[:, :, :3][alpha > 0] = palette[idx]
    else:
        palette = np.empty((0, 3), dtype=np.uint8); stride = 1
        quantizer = 'none'
        result = np.zeros_like(arr)
    Image.fromarray(result).save(out / 'regions.png')
    Image.fromarray(alpha).save(out / 'alpha.png')
    np.save(out / 'labels.npy', labels, allow_pickle=False)
    meta.update(requested_colors=colors, palette_rgb=palette.tolist(), sample_stride=stride,
                quantizer=quantizer, alpha_policy='unchanged_separate_channel', dither=False, resized=False,
                status='proposal_only', note='Color labels are not connected components or a shared boundary graph')
    save_json(out / 'palette.json', meta)
    return meta


def compare(source, rendered, out, frame=None):
    a, source_meta = load_image(source, frame)
    b, rendered_meta = load_image(rendered)
    if a.size != b.size:
        raise ValueError(f'Dimension mismatch {a.size} != {b.size}; no implicit resizing')
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    av, bv = np.asarray(a).astype(np.float32) / 255, np.asarray(b).astype(np.float32) / 255
    aa, ba = av[:, :, 3], bv[:, :, 3]
    ac, bc = av[:, :, :3] * aa[:, :, None], bv[:, :, :3] * ba[:, :, None]
    delta = bc - ac; ad = ba - aa
    union = (aa >= .5) | (ba >= .5)
    intersection = (aa >= .5) & (ba >= .5)
    metrics = {'premultiplied_rgb_mae': float(np.abs(delta).mean()),
               'premultiplied_rgb_rmse': float(np.sqrt(np.square(delta).mean())),
               'premultiplied_rgb_max': float(np.abs(delta).max()),
               'alpha_mae': float(np.abs(ad).mean()), 'alpha_max_deficit': float(np.maximum(-ad, 0).max()),
               'alpha_max_excess': float(np.maximum(ad, 0).max()),
               'silhouette_iou': float(intersection.sum() / union.sum()) if union.any() else None,
               'silhouette_threshold': .5, 'silhouette_informative': bool((aa < .5).any())}
    heat = np.maximum(np.abs(delta).max(axis=2), np.abs(ad))
    Image.fromarray(np.uint8(np.clip(heat * 4, 0, 1) * 255)).save(out / 'difference.png')
    Image.fromarray(np.uint8(np.clip(np.abs(ad) * 4, 0, 1) * 255)).save(out / 'alpha-difference.png')
    rows = []
    for name, bg in [('white', (1, 1, 1)), ('black', (0, 0, 0)), ('color', (75/255, 135/255, 197/255))]:
        x = ac + (1-aa[:, :, None]) * np.array(bg)
        y = bc + (1-ba[:, :, None]) * np.array(bg)
        d = np.clip(np.abs(x-y) * 4, 0, 1)
        row = Image.fromarray(np.uint8(np.clip(np.concatenate([x, y, d], axis=1), 0, 1)*255))
        row.save(out / f'comparison-{name}.png'); rows.append(row)
    panel = Image.new('RGB', (a.width * 3, a.height * 3))
    for i, row in enumerate(rows): panel.paste(row, (0, a.height*i))
    panel.save(out / 'comparison.png')
    y, x = np.unravel_index(int(heat.argmax()), heat.shape)
    box = (max(0, x-32), max(0, y-32), min(a.width, x+33), min(a.height, y+33))
    crop_a, crop_b = a.crop(box), b.crop(box)
    crop = Image.new('RGBA', (crop_a.width*2, crop_a.height))
    crop.paste(crop_a); crop.paste(crop_b, (crop_a.width, 0)); crop.save(out / 'worst-crop.png')
    report = {'source': source_meta, 'rendered': rendered_meta, 'metrics': metrics,
              'worst_crop_box': list(map(int, box)), 'measurement_space': 'encoded_sRGB_premultiplied_0_to_1',
              'measurement_status': 'passed', 'quality_status': 'indeterminate',
              'notes': ['No universal fidelity threshold applied', 'Background panels composite averaged RGBA, not subpixel ground truth']}
    save_json(out / 'comparison.json', report)
    return report
