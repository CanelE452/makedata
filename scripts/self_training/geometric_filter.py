"""Geometric Filter for pseudo-label validation in self-training.

Validates whether a predicted 6D pose and its corresponding 2D keypoints
form a geometrically plausible cuboid. This replaces the confidence
threshold in FixMatch, adapted for keypoint regression tasks.

Three conditions are checked:
  1. Reprojection error: EPnP solution must project back close to detections.
  2. Cuboid geometry:   opposite edges should have similar lengths,
                        adjacent edges should meet at near-right angles.
  3. Size validation:   estimated pallet physical size must be in range.

Usage:
    gf = GeometricFilter(pnp_solver, cfg)
    is_valid, details = gf.validate(keypoints_2d, R, t)
"""

import numpy as np

from pnp_solver import PalletPnPSolver


class GeometricFilter:
    """Validate pseudo-labels using geometric consistency checks."""

    def __init__(self, pnp_solver, config=None):
        """
        Args:
            pnp_solver: PalletPnPSolver instance (for reprojection).
            config: dict with threshold values. Uses defaults if None.
        """
        self.pnp_solver = pnp_solver

        cfg = config or {}
        self.tau_reproj = cfg.get("tau_reproj", 5.0)
        self.tau_ratio_min = cfg.get("tau_ratio_min", 0.5)
        self.tau_ratio_max = cfg.get("tau_ratio_max", 2.0)
        self.tau_angle_min = cfg.get("tau_angle_min", 60.0)
        self.tau_angle_max = cfg.get("tau_angle_max", 120.0)
        self.tau_size_min = cfg.get("tau_size_min", 0.5)
        self.tau_size_max = cfg.get("tau_size_max", 2.5)
        self.min_keypoints = cfg.get("min_keypoints", 5)

    def validate(self, keypoints_2d, R, t):
        """Run all three geometric checks on a pseudo-label.

        Args:
            keypoints_2d: list of 9 elements, each (u, v) or None.
            R: (3, 3) rotation matrix from PnP.
            t: (3,) translation vector from PnP.

        Returns:
            is_valid: bool, True if all conditions pass.
            details: dict with per-condition results for logging.
        """
        details = {
            "condition_1_reproj": False,
            "condition_2_geometry": False,
            "condition_3_size": False,
            "reproj_error_mean": float("inf"),
            "estimated_size": 0.0,
        }

        # Count valid keypoints
        valid_kps = self._get_valid_keypoints(keypoints_2d)
        if len(valid_kps) < self.min_keypoints:
            return False, details

        # Condition 1: Reprojection error
        c1, reproj_err = self._check_reprojection(keypoints_2d, R, t)
        details["condition_1_reproj"] = c1
        details["reproj_error_mean"] = reproj_err

        # Condition 2: Cuboid geometry on the reprojected points
        reprojected = self.pnp_solver.reproject(R, t)
        c2 = self._check_cuboid_geometry(reprojected[:8])
        details["condition_2_geometry"] = c2

        # Condition 3: Physical size
        c3, est_size = self._check_size(R, t)
        details["condition_3_size"] = c3
        details["estimated_size"] = est_size

        return (c1 and c2 and c3), details

    def _get_valid_keypoints(self, keypoints_2d):
        """Return indices of valid (non-None, non-negative) keypoints."""
        valid = []
        for i, pt in enumerate(keypoints_2d):
            if pt is None:
                continue
            if hasattr(pt, '__len__') and len(pt) >= 2:
                if pt[0] >= 0 and pt[1] >= 0:
                    valid.append(i)
        return valid

    def _check_reprojection(self, keypoints_2d, R, t):
        """Condition 1: mean reprojection error must be below threshold.

        Compares detected 2D keypoints against PnP-reprojected 3D keypoints.
        Only valid (detected) keypoints are included in the error computation.
        """
        reprojected = self.pnp_solver.reproject(R, t)
        errors = []
        for i in range(9):
            if i >= len(keypoints_2d):
                continue
            pt = keypoints_2d[i]
            if pt is None:
                continue
            if hasattr(pt, '__len__') and len(pt) >= 2:
                u, v = float(pt[0]), float(pt[1])
                if u < 0 or v < 0:
                    continue
                err = np.sqrt((u - reprojected[i, 0]) ** 2 +
                              (v - reprojected[i, 1]) ** 2)
                errors.append(err)

        if len(errors) == 0:
            return False, float("inf")

        mean_err = float(np.mean(errors))
        return mean_err < self.tau_reproj, mean_err

    def _check_cuboid_geometry(self, corners_2d):
        """Condition 2: cuboid edge ratios and adjacent angles.

        Checks that:
          a) Opposite edges of each face have similar lengths.
          b) Adjacent edges meet at approximately 90 degrees.
        """
        pts = np.array(corners_2d, dtype=np.float64)  # (8, 2)

        # -- Edge ratio check --
        # Opposite edge pairs on a cuboid. Each tuple is ((i,j), (k,l))
        # where edge (i->j) should have similar length to edge (k->l).
        opposite_pairs = [
            # Front face
            ((0, 1), (3, 2)),  # top vs bottom
            ((0, 3), (1, 2)),  # right vs left
            # Rear face
            ((4, 5), (7, 6)),  # top vs bottom
            ((4, 7), (5, 6)),  # right vs left
            # Side edges (front-to-rear)
            ((0, 4), (1, 5)),
            ((3, 7), (2, 6)),
        ]

        for (a, b), (c, d) in opposite_pairs:
            len_ab = np.linalg.norm(pts[a] - pts[b])
            len_cd = np.linalg.norm(pts[c] - pts[d])
            if len_ab < 1e-6 or len_cd < 1e-6:
                return False
            ratio = len_ab / len_cd
            if ratio < self.tau_ratio_min or ratio > self.tau_ratio_max:
                return False

        # -- Adjacent angle check --
        # Check angles at selected corners where two edges meet.
        # For a cuboid projection, angles should be roughly 60-120 degrees
        # (exact 90 only when viewed head-on).
        adjacent_triples = [
            # (prev, corner, next) — angle is measured at 'corner'
            (1, 0, 3),   # Front face, top-right corner
            (0, 1, 2),   # Front face, top-left corner
            (5, 4, 7),   # Rear face, top-right corner
            (4, 5, 6),   # Rear face, top-left corner
            (1, 0, 4),   # Top-right, front-to-rear
            (2, 3, 7),   # Bottom-right, front-to-rear
        ]

        for p, c, n in adjacent_triples:
            angle = self._angle_at_vertex(pts[p], pts[c], pts[n])
            if angle < self.tau_angle_min or angle > self.tau_angle_max:
                return False

        return True

    @staticmethod
    def _angle_at_vertex(p1, vertex, p2):
        """Compute angle in degrees at 'vertex' formed by p1-vertex-p2."""
        v1 = p1 - vertex
        v2 = p2 - vertex
        n1 = np.linalg.norm(v1)
        n2 = np.linalg.norm(v2)
        if n1 < 1e-6 or n2 < 1e-6:
            return 0.0
        cos_angle = np.dot(v1, v2) / (n1 * n2)
        cos_angle = np.clip(cos_angle, -1.0, 1.0)
        return float(np.degrees(np.arccos(cos_angle)))

    def _check_size(self, R, t):
        """Condition 3: estimated pallet size must be physically plausible.

        Computes the pallet width in meters from the translation depth
        and the projected width in pixels. The estimated width should be
        close to the known pallet width (e.g. 1.1m).
        """
        keypoints_3d = self.pnp_solver.keypoints_3d[:8]

        # Transform 3D keypoints to camera frame
        pts_cam = (R @ keypoints_3d.T).T + t  # (8, 3)

        # Compute physical width: distance between front-top-right (0) and
        # front-top-left (1) in 3D camera coordinates
        width_3d = np.linalg.norm(pts_cam[0] - pts_cam[1])

        return (self.tau_size_min < width_3d < self.tau_size_max), float(width_3d)
