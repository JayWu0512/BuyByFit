"""Camera + floor for one room photo, from the phone's sensors (no GPU, instant).

The in-page camera records the phone's tilt (DeviceOrientation beta) at the shutter. With the iPhone main
camera's field of view and a typical phone height, that fixes the camera relative to the floor (y = 0).
Without a tilt (library photo) we use typical values. Measured on real photos with MapAnything: 67.3 deg
vertical FOV (portrait 3:4), phone ~1.5-1.7 m above the floor.

World: metres, floor y=0, three.js camera conventions (looks -Z, +Y up).
"""

from __future__ import annotations

import math

import numpy as np

IPHONE_MAIN_FOV_Y = 67.3
DEFAULT_PHONE_HEIGHT_M = 1.5
DEFAULT_PITCH_DEG = 12.0


def scene_from_sensors(width: int, height: int, pitch_deg: float | None, phone_height_m: float | None = None) -> dict:
    pitch = DEFAULT_PITCH_DEG if pitch_deg is None else max(-60.0, min(89.0, float(pitch_deg)))
    cam_h = DEFAULT_PHONE_HEIGHT_M if phone_height_m is None else max(0.5, min(2.5, float(phone_height_m)))
    if height >= width:
        fov_y = IPHONE_MAIN_FOV_Y
    else:  # landscape: same lens, the long side is now horizontal
        fov_y = math.degrees(2 * math.atan(math.tan(math.radians(IPHONE_MAIN_FOV_Y) / 2) * height / width))
    a = math.radians(-pitch)  # negative rotation about X looks down
    return {
        "photo_size": [width, height],
        "fov_y_deg": round(fov_y, 2),
        "camera": {"position": [0.0, cam_h, 0.0], "quaternion": [math.sin(a / 2), 0.0, 0.0, math.cos(a / 2)]},
        "pitch_deg": round(pitch, 1),
        "source": "sensors" if pitch_deg is not None else "defaults",
    }


def _quat_matrix(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


class Camera:
    """Project world points to the photo and cast rays from photo pixels onto the floor."""

    def __init__(self, scene: dict):
        self.pos = np.array(scene["camera"]["position"], float)
        self.R = _quat_matrix(scene["camera"]["quaternion"])  # camera -> world
        w, h = scene["photo_size"]
        self.ty = math.tan(math.radians(scene["fov_y_deg"]) / 2)
        self.tx = self.ty * w / h

    def project(self, p):
        """World point -> (u, v) in 0..1 of the image, or None if behind the camera."""
        c = self.R.T @ (np.asarray(p, float) - self.pos)
        if c[2] >= -1e-3:
            return None
        return ((c[0] / -c[2]) / self.tx + 1) / 2, (1 - (c[1] / -c[2]) / self.ty) / 2

    def floor_point(self, u, v):
        """Image point (0..1) -> point on the floor, or None if the ray doesn't hit the floor."""
        d = self.R @ np.array([(2 * u - 1) * self.tx, (1 - 2 * v) * self.ty, -1.0])
        if d[1] >= -1e-6:
            return None
        return self.pos + (-self.pos[1] / d[1]) * d
