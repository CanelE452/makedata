"""EPnP + RANSAC wrapper for 6D pose recovery from 2D keypoints.

Defines the standard pallet 3D keypoints (KS T 1002: 1100x1100x150mm)
and provides a clean interface for pose estimation via OpenCV solvePnP.

Usage:
    solver = PalletPnPSolver(camera_matrix, pallet_dims=(1.1, 1.1, 0.15))
    success, R, t, inliers = solver.solve(keypoints_2d)
"""

import cv2
import numpy as np


# Cuboid vertex ordering follows NDDS / DOPE convention (see cuboid.py):
#   0: FrontTopRight     4: RearTopRight
#   1: FrontTopLeft      5: RearTopLeft
#   2: FrontBottomLeft   6: RearBottomLeft
#   3: FrontBottomRight  7: RearBottomRight
#   8: Centroid

def make_pallet_keypoints_3d(width=1.1, depth=1.1, height=0.15):
    """Generate 9 keypoints (8 cuboid corners + centroid) in object frame.

    Uses OpenCV camera convention where the object coordinate system has:
      - X axis: right
      - Y axis: down
      - Z axis: forward

    This matches how DOPE's Cuboid3d.generate_vertexes() defines vertices
    when coord_system is None (default OpenCV convention).

    Args:
        width:  pallet width along X axis (meters).
        depth:  pallet depth along Z axis (meters).
        height: pallet height along Y axis (meters).

    Returns:
        np.ndarray of shape (9, 3).
    """
    w, h, d = width / 2.0, height / 2.0, depth / 2.0

    # right/left along X, top/bottom along Y, front/rear along Z
    right, left = w, -w
    top, bottom = -h, h
    front, rear = d, -d

    corners = np.array([
        [right, top, front],      # 0: FrontTopRight
        [left,  top, front],      # 1: FrontTopLeft
        [left,  bottom, front],   # 2: FrontBottomLeft
        [right, bottom, front],   # 3: FrontBottomRight
        [right, top, rear],       # 4: RearTopRight
        [left,  top, rear],       # 5: RearTopLeft
        [left,  bottom, rear],    # 6: RearBottomLeft
        [right, bottom, rear],    # 7: RearBottomRight
    ], dtype=np.float64)

    centroid = corners.mean(axis=0, keepdims=True)  # (1, 3)
    return np.vstack([corners, centroid])            # (9, 3)


def make_camera_matrix(fx, fy, cx, cy):
    """Build 3x3 camera intrinsic matrix."""
    return np.array([
        [fx,  0, cx],
        [ 0, fy, cy],
        [ 0,  0,  1],
    ], dtype=np.float64)


class PalletPnPSolver:
    """Solve pallet 6D pose from 2D keypoint detections via EPnP + RANSAC."""

    def __init__(self, camera_matrix, dist_coeffs=None,
                 pallet_dims=(1.1, 1.1, 0.15),
                 use_ransac=True, ransac_reproj_threshold=8.0,
                 ransac_iterations=100):
        """
        Args:
            camera_matrix: 3x3 intrinsic matrix.
            dist_coeffs:   distortion coefficients (default: zero).
            pallet_dims:   (width, depth, height) in meters.
            use_ransac:    whether to use RANSAC variant.
            ransac_reproj_threshold: inlier threshold in pixels.
            ransac_iterations: max RANSAC iterations.
        """
        self.camera_matrix = np.array(camera_matrix, dtype=np.float64)
        self.dist_coeffs = (np.array(dist_coeffs, dtype=np.float64)
                            if dist_coeffs is not None
                            else np.zeros((4, 1), dtype=np.float64))
        self.keypoints_3d = make_pallet_keypoints_3d(*pallet_dims)
        self.use_ransac = use_ransac
        self.ransac_reproj_threshold = ransac_reproj_threshold
        self.ransac_iterations = ransac_iterations

    def solve(self, keypoints_2d):
        """Estimate 6D pose from 2D keypoint detections.

        Args:
            keypoints_2d: list of 9 elements. Each element is either
                (u, v) tuple or None if the keypoint was not detected.

        Returns:
            success: bool, whether PnP succeeded.
            R: (3, 3) rotation matrix (world-to-camera).
            t: (3,) translation vector.
            inliers: array of inlier indices, or None.
        """
        obj_2d = []
        obj_3d = []
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
                obj_2d.append([u, v])
                obj_3d.append(self.keypoints_3d[i])

        if len(obj_2d) < 4:
            return False, None, None, None

        obj_2d = np.array(obj_2d, dtype=np.float64)
        obj_3d = np.array(obj_3d, dtype=np.float64)

        inliers = None
        if self.use_ransac:
            success, rvec, tvec, inliers = cv2.solvePnPRansac(
                obj_3d, obj_2d,
                self.camera_matrix, self.dist_coeffs,
                flags=cv2.SOLVEPNP_EPNP,
                reprojectionError=self.ransac_reproj_threshold,
                iterationsCount=self.ransac_iterations,
            )
        else:
            success, rvec, tvec = cv2.solvePnP(
                obj_3d, obj_2d,
                self.camera_matrix, self.dist_coeffs,
                flags=cv2.SOLVEPNP_EPNP,
            )

        if not success:
            return False, None, None, None

        R, _ = cv2.Rodrigues(rvec)
        t = tvec.flatten()

        # Flip if object is behind camera (z < 0)
        if t[2] < 0:
            t = -t
            R = -R

        return True, R, t, inliers

    def reproject(self, R, t):
        """Reproject all 9 3D keypoints onto image plane.

        Args:
            R: (3, 3) rotation matrix.
            t: (3,) translation vector.

        Returns:
            np.ndarray of shape (9, 2) with pixel coordinates.
        """
        rvec, _ = cv2.Rodrigues(R)
        projected, _ = cv2.projectPoints(
            self.keypoints_3d, rvec, t.reshape(3, 1),
            self.camera_matrix, self.dist_coeffs,
        )
        return projected.reshape(-1, 2)
