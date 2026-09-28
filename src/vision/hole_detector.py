"""Measure the five top-face Mother holes inside a YOLO Mother OBB.

The Mother is warped to a horizontal crop. Around each nominal hole position
(config hole_alphas) the darkest blob is located, so the returned positions are
real measurements, not the nominal ratios. A hole covered by a bolt, a part,
a hand, or a Mother lying on its 2-hole side face is reported as not visible.

Coordinates:
  alpha = offset along the Mother long axis / Mother long length   (H1 < 0 < H5)
  beta  = offset along the Mother short axis / Mother short length
"""
from dataclasses import dataclass
from math import degrees

import cv2
import numpy as np

from src.geometry.mother_frame import major_axis
from src.geometry.mother_registration import registration_config


@dataclass(frozen=True)
class HoleObservation:
    hole_id: int
    x: float            # original-image pixels
    y: float
    alpha: float
    beta: float
    contrast: float     # 1 - mean(hole disk)/surface brightness; ~0.9 for an open hole
    visible: bool


@dataclass(frozen=True)
class HoleMeasurement:
    holes: tuple[HoleObservation, ...]
    surface: float

    @property
    def visible_count(self):
        return sum(h.visible for h in self.holes)


def _crop(image, detection, margin):
    width, height, angle = major_axis(detection)
    cx, cy = detection.center_xy
    out_w = int(round(width*(1+margin)))
    out_h = int(round(height*(1+2*margin)))
    matrix = cv2.getRotationMatrix2D((cx, cy), degrees(angle), 1.0)
    matrix[0, 2] += out_w/2 - cx
    matrix[1, 2] += out_h/2 - cy
    crop = cv2.warpAffine(image, matrix, (out_w, out_h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)
    return crop, cv2.invertAffineTransform(matrix), width, height


def _fit_line(good, nominal):
    """Robust x = x0 + i*step over (index, x) pairs; None if under-determined."""
    if len(good) < 3:
        return None
    nominal_step = (nominal[-1]-nominal[0])/(len(nominal)-1)
    best = None
    for (i, xi), (j, xj) in ((p, q) for p in good for q in good if q[0] > p[0]):
        step = (xj-xi)/(j-i)
        if not 0.7*nominal_step <= step <= 1.3*nominal_step:
            continue
        x0 = xi - i*step
        inliers = [(k, x) for k, x in good if abs(x-(x0+k*step)) < 0.2*step]
        error = sum(abs(x-(x0+k*step)) for k, x in inliers)
        if best is None or (len(inliers), -error) > (len(best), -best_error):
            best, best_error = inliers, error
    if best is None or len(best) < 3:
        return None
    step, x0 = np.polyfit([k for k, _ in best], [x for _, x in best], 1)
    return [x0 + step*i for i in range(len(nominal))]


def measure_holes(image, detection, config):
    """image: BGR ndarray in original pixels; detection: mother_part OBBDetection."""
    reg = registration_config(config)
    crop, inverse, width, height = _crop(image, detection, reg["crop_margin_ratio"])
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray = cv2.GaussianBlur(gray, (0, 0), max(1.0, height*0.03))
    crop_h, crop_w = gray.shape
    cx, cy = crop_w/2, crop_h/2
    # Only search inside the Mother body so background never counts as a hole.
    x_lo, x_hi = int(cx-0.48*width), int(cx+0.48*width)
    y_lo, y_hi = int(cy-0.38*height), int(cy+0.38*height)
    body = gray[y_lo:y_hi, x_lo:x_hi]
    surface = float(np.percentile(body, 80)) if body.size else 0.0
    window = reg["hole_search_ratio"]*width
    radius = max(2, int(height*0.15))
    ys_all, xs_all = np.mgrid[0:crop_h, 0:crop_w]

    def search(xc):
        x0, x1 = int(max(x_lo, xc-window)), int(min(x_hi, xc+window))
        roi = gray[y_lo:y_hi, x0:x1]
        if surface <= 0 or not roi.size:
            return xc, cy, 0.0
        dark = np.clip(surface*0.6 - roi, 0, None)
        if dark.sum() < 1e-6:
            return xc, cy, 0.0
        xs, ys = xs_all[y_lo:y_hi, x0:x1], ys_all[y_lo:y_hi, x0:x1]
        x = float((xs*dark).sum()/dark.sum())
        y = float((ys*dark).sum()/dark.sum())
        disk = np.zeros(gray.shape, np.uint8)
        cv2.circle(disk, (int(round(x)), int(round(y))), radius, 1, -1)
        return x, y, float(1 - gray[disk > 0].mean()/surface)

    nominal = [cx + a*width for a in config["hole_alphas"]]
    first = [search(xc) for xc in nominal]
    # Pass 2: the OBB length/centre can be a few % off, which pushes the end
    # windows off the real H1/H5. Fit x = x0 + i*step on the clearly open holes
    # and search again around the fitted positions.
    good = [(i, r[0]) for i, r in enumerate(first) if r[2] >= reg["hole_min_contrast"]]
    centres = _fit_line(good, nominal) or nominal
    holes = []
    for hole_id, xc in enumerate(centres, 1):
        x, y, contrast = search(xc)
        px, py = inverse @ np.array([x, y, 1.0])
        holes.append(HoleObservation(hole_id, float(px), float(py),
                                     round((x-cx)/width, 4), round((y-cy)/height, 4),
                                     round(contrast, 3), contrast >= reg["hole_min_contrast"]))
    return HoleMeasurement(tuple(holes), surface)
