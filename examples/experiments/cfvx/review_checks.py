"""Reproducible, limited numerical checks for the CFV-X design review.

These checks are NOT a full raster-to-vector implementation or an industry
benchmark. The inverse-circle test uses a matched synthetic forward model.
Dependencies: numpy, scipy, scikit-image. Run: python review_checks.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import numpy as np
import scipy
import skimage
from scipy.integrate import quad
from scipy.optimize import least_squares
from scipy.ndimage import gaussian_filter
from skimage.measure import find_contours


def circle_coverage(theta: np.ndarray, size: int = 32) -> np.ndarray:
    """Box-filter coverage using adaptive 1D quadrature at boundary pixels.

    Pixel (row, col) is [col,col+1] x [row,row+1]. This is a numerical reference,
    NOT an outward-rounded mathematical certificate of integration error.
    """
    cx, cy, r = map(float, theta)
    if not (r > 0 and np.all(np.isfinite(theta))):
        raise ValueError("Circle parameters must be finite and radius positive")
    yy, xx = np.mgrid[:size, :size]
    nearx = np.maximum(np.maximum(xx - cx, cx - (xx + 1)), 0.0)
    neary = np.maximum(np.maximum(yy - cy, cy - (yy + 1)), 0.0)
    farx = np.maximum(np.abs(xx - cx), np.abs(xx + 1 - cx))
    fary = np.maximum(np.abs(yy - cy), np.abs(yy + 1 - cy))
    inside = farx * farx + fary * fary <= r * r
    outside = nearx * nearx + neary * neary >= r * r
    result = inside.astype(float)
    boundary = np.argwhere(~inside & ~outside)
    for row, col in boundary:
        x0, x1, y0, y1 = float(col), float(col + 1), float(row), float(row + 1)
        lo, hi = max(x0, cx - r), min(x1, cx + r)
        if hi <= lo:
            continue
        cuts = []
        for y in (y0, y1):
            rad = r * r - (y - cy) ** 2
            if rad > 0:
                dx = math.sqrt(rad)
                cuts.extend(x for x in (cx - dx, cx + dx) if lo < x < hi)

        def height(x: float) -> float:
            dy = math.sqrt(max(0.0, r * r - (x - cx) ** 2))
            return max(0.0, min(y1, cy + dy) - max(y0, cy - dy))

        area, _ = quad(height, lo, hi, points=sorted(set(cuts)),
                       epsabs=1e-10, epsrel=1e-10, limit=80)
        result[row, col] = np.clip(area, 0.0, 1.0)
    return result


def edge_fit(image: np.ndarray) -> np.ndarray:
    contours = find_contours(image, 0.5)
    if not contours:
        raise RuntimeError("No contour")
    rc = max(contours, key=len)
    pts = rc[:, ::-1] + 0.5
    center = pts.mean(axis=0)
    r0 = np.linalg.norm(pts - center, axis=1).mean()
    fit = least_squares(lambda p: np.linalg.norm(pts - p[:2], axis=1) - p[2],
                        np.r_[center, r0], xtol=1e-12, ftol=1e-12, gtol=1e-12)
    if not fit.success:
        raise RuntimeError(fit.message)
    return fit.x


def main() -> None:
    out = {
        "scope": "limited numerical sanity checks, not a complete vectorizer benchmark",
        "seed": 20260908,
        "versions": {"numpy": np.__version__, "scipy": scipy.__version__,
                     "skimage": skimage.__version__},
    }
    edge_positions = np.array([0.2501, 0.2502])
    codes = np.rint(255 * (1 - edge_positions)).astype(int)
    assert codes[0] == codes[1]
    out["quantization_nonuniqueness"] = {"positions": edge_positions.tolist(),
                                           "uint8_codes": codes.tolist()}

    out["short_arc_information"] = []
    n, noise = 121, 0.02
    for degrees in (360, 180, 60, 15, 5):
        a = np.deg2rad(degrees)
        phi = (np.linspace(-a / 2, a / 2, n, endpoint=degrees != 360))
        j = np.column_stack((-np.cos(phi), -np.sin(phi), -np.ones(n)))
        covariance = noise**2 * np.linalg.inv(j.T @ j)
        out["short_arc_information"].append({
            "span_degrees": degrees, "n": n, "normal_noise_sigma_px": noise,
            "condition_number_J": float(np.linalg.cond(j)),
            "local_linearized_radius_sigma_px": float(np.sqrt(covariance[2, 2]))})

    rng = np.random.default_rng(20260908)
    pts = rng.normal(size=(100, 2))
    center, r = np.array([0.2, -0.3]), 1.7
    phi = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    projected = center + r * np.column_stack((np.cos(phi), np.sin(phi)))
    angular_objective = np.sum((pts - projected)**2, axis=1)
    radial_objective = (np.linalg.norm(pts - center, axis=1) - r)**2
    identity_error = float(np.max(np.abs(angular_objective - radial_objective)))
    assert identity_error < 1e-12
    out["latent_angles_equal_geometric_distance"] = {"max_abs_error": identity_error}

    m = np.array([[1., 0.], [0.5, 0.5], [0., 1.]])
    cov = m @ m.T
    jac = np.ones(3)
    information = float(jac @ np.linalg.pinv(cov) @ jac)
    assert abs(information - 2) < 1e-12
    out["interpolation_adds_no_independent_information"] = {
        "original_information": 2.0, "naive_independent_information": 3.0,
        "covariance_aware_information": information, "covariance_rank": int(np.linalg.matrix_rank(cov))}

    y = np.array([0., 0., 0., 4.])
    out["least_squares_failure_is_not_infeasibility"] = {
        "family": "horizontal line y=b", "observations_y": y.tolist(), "epsilon": 2.0,
        "least_squares_b": float(y.mean()), "least_squares_max_error": float(np.max(abs(y-y.mean()))),
        "minimax_b": 2.0, "minimax_max_error": 2.0}

    out["shared_edge_alpha"] = {"each_shape_coverage": 0.5,
        "independently_composited_alpha": 0.5 + 0.5*(1-0.5),
        "joint_partition_coverage": 1.0,
        "note": "algebraic counterexample, not a browser measurement"}

    out["sampled_curve_validation_failure"] = {
        "curve": "(t, 0.2*sin(pi*t)^2), t in [0,1]", "reference": "(t,0)",
        "sampled_t": [0.0, 1.0], "sampled_max_distance": 0.0,
        "continuous_max_distance": 0.2}
    out["sagitta"] = [{"r_px": 100.0, "span_degrees": deg,
                       "max_arc_to_chord_px": 100*(1-math.cos(math.radians(deg)/2))}
                       for deg in (5, 10)]

    truth = np.array([15.23, 15.67, 8.3])
    clean = circle_coverage(truth)
    observed = np.rint(clean * 255) / 255
    initial = edge_fit(observed)
    pixel_fit = least_squares(lambda p: (circle_coverage(p)-observed).ravel(), initial,
                             bounds=([0,0,0.1], [32,32,30]),
                             xtol=1e-10, ftol=1e-10, gtol=1e-10, max_nfev=50)
    if not pixel_fit.success:
        raise RuntimeError(pixel_fit.message)
    out["matched_forward_single_circle"] = {
        "truth_cx_cy_r": truth.tolist(), "image_size": [32,32], "quantization_bits": 8,
        "noise_added": False, "psf": "none; box pixel coverage only",
        "forward_model": "adaptive 1D quadrature, epsabs=epsrel=1e-10",
        "fit_objective": "pixel least squares on decoded quantized midpoints, not quantization-interval MLE",
        "point_fit": initial.tolist(), "pixel_fit": pixel_fit.x.tolist(),
        "point_fit_center_error_px": float(np.linalg.norm(initial[:2]-truth[:2])),
        "point_fit_radius_error_px": float(abs(initial[2]-truth[2])),
        "pixel_fit_center_error_px": float(np.linalg.norm(pixel_fit.x[:2]-truth[:2])),
        "pixel_fit_radius_error_px": float(abs(pixel_fit.x[2]-truth[2])),
        "limitation": "one matched synthetic example, no claim about real-world images"}

    outpath = Path(__file__).with_name('review_checks_results.json')
    outpath.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
