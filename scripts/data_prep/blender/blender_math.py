"""좌표 변환, 투영, 쿼터니언 등 수학 헬퍼."""

import numpy as np


def euler_to_rotation_matrix(euler_deg):
    """XYZ intrinsic Euler angles (degrees) -> 3x3 rotation matrix."""
    rx, ry, rz = np.radians(euler_deg)
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def rotation_matrix_to_quat_xyzw(R):
    """3x3 rotation matrix -> [qx, qy, qz, qw]."""
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    return [float(x), float(y), float(z), float(w)]


def rotation_matrix_to_euler_deg(R):
    """3x3 rotation matrix -> (pitch, yaw, roll) in degrees."""
    sy = np.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    singular = sy < 1e-6
    if not singular:
        x = np.arctan2(R[2, 1], R[2, 2])
        y = np.arctan2(-R[2, 0], sy)
        z = np.arctan2(R[1, 0], R[0, 0])
    else:
        x = np.arctan2(-R[1, 2], R[1, 1])
        y = np.arctan2(-R[2, 0], sy)
        z = 0
    return float(np.degrees(x)), float(np.degrees(y)), float(np.degrees(z))


def build_view_matrix(cam_pos, look_at_target, up=(0, 0, 1)):
    """cam_pos + look_at -> world-to-camera (R, t). OpenCV convention."""
    cam_pos = np.array(cam_pos, dtype=np.float64)
    target = np.array(look_at_target, dtype=np.float64)
    up = np.array(up, dtype=np.float64)

    forward = target - cam_pos
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, up)
    norm_r = np.linalg.norm(right)
    if norm_r < 1e-6:
        up = np.array([0, 1, 0], dtype=np.float64)
        right = np.cross(forward, up)
        norm_r = np.linalg.norm(right)
    right = right / norm_r
    cam_up = np.cross(right, forward)

    R_w2c = np.array([right, -cam_up, forward], dtype=np.float64)
    t_w2c = -R_w2c @ cam_pos
    return R_w2c, t_w2c


def canonical_corners_yup(bbox_min, bbox_max):
    """Canonical bbox (Y=UP) -> 8 DOPE corners.
    Order: 0=FTR, 1=FTL, 2=FBL, 3=FBR, 4=RTR, 5=RTL, 6=RBL, 7=RBR."""
    mn, mx = np.array(bbox_min), np.array(bbox_max)
    return np.array([
        [mn[0], mx[1], mx[2]],
        [mx[0], mx[1], mx[2]],
        [mx[0], mn[1], mx[2]],
        [mn[0], mn[1], mx[2]],
        [mn[0], mx[1], mn[2]],
        [mx[0], mx[1], mn[2]],
        [mx[0], mn[1], mn[2]],
        [mn[0], mn[1], mn[2]],
    ])


def yup_to_zup(pts):
    """Y=UP -> Blender Z=UP coordinate conversion."""
    out = np.zeros_like(pts)
    out[..., 0] = pts[..., 0]
    out[..., 1] = -pts[..., 2]
    out[..., 2] = pts[..., 1]
    return out


def _polyarea_2d(pts2d):
    """Shoelace area of a 2D polygon (vertices in given order)."""
    x = pts2d[:, 0]
    y = pts2d[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _face_outward_normal(face_pts, centroid):
    """면 4 corner(3D, 순회 순서) -> outward unit normal.

    Newell 법으로 평면 법선을 구하고, centroid 기준 바깥쪽으로 부호를 정렬한다.
    평평한 팔레트의 두 side 면은 거의 정반대 방향 normal 을 가진다."""
    P = np.asarray(face_pts, dtype=np.float64)
    n = np.zeros(3)
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    nn = np.linalg.norm(n)
    if nn < 1e-12:
        return n
    n = n / nn
    if np.dot(n, P.mean(axis=0) - centroid) < 0:
        n = -n
    return n


def _wrap_deg(a):
    """각도(도)를 (-180, 180] 로 wrap."""
    return (a + 180.0) % 360.0 - 180.0


# 검증 한계: 신·구 일치는 앙각 ≤60° 구간에서만 검증됨. 방위각 규칙의 핵심 이점(고앙각에서
# 게이트 완화 없이 판정)은 미검증이며, 파일럿에서 60~80° bin을 처음 돌릴 때 확인한다.
def compute_perm_v4(corners_world, uv8, cam_pos=None, return_margin=False):
    """카메라 기준 동적 0123 keypoint ID 재배정 (compute_perm_v4).

    입력
        corners_world : (8,3) world-space cuboid corner (임의 순서, get_pallet_geometry 출력)
        uv8           : (8,2) 위 corner 들을 이미지에 투영한 좌표 (corners_world 와 같은 순서)
        cam_pos       : (3,) 카메라 월드 좌표. FRONT 판정 기준.
                        FRONT = 옆면 outward normal 의 방위각(월드 XY)이 (파렛트 중심->카메라)
                        방향 방위각 φ_cam 과 가장 가까운 side 면 (argmin |φ_cam - φ_face|).
                        [2026-07-24 승인] 옛 normal-facing(3D dot 최대) 규칙은 고앙각에서 FRONT
                        면이 grazing 이 되어 front_cos 게이트로 자동 기각되는 문제가 있었다.
                        방위각 규칙은 앙각(카메라 높이) 무관하게 4옆면 중 카메라를 마주보는 면을
                        고른다. 접지(roll·pitch≈0) 가정. None 이면 면적 fallback.

        return_margin : True 면 (perm, facing_margin, front_cos) 튜플 반환.
                        facing_margin = 45 - |Δφ| (★ 단위: 도[deg], ∈[0, 45]), Δφ = φ_cam -
                        선택된 FRONT normal 의 방위각. 45=정면(head-on), 0=45° 코너온(인접 두
                        면 애매). [주의: 2026-07-24 방위각 규칙 도입으로 정의가 옛 best-minus-
                        second cos 차이[0, 2] 에서 도[0, 45] 로 바뀜 → 호출부 FACING_MARGIN_MIN
                        을 도 기준으로 재보정 필요.]
                        front_cos 는 FRONT(방위각으로 선택된 면) 자체의 3D 정면도
                        = dot(n_front, unit(cam - front_face_center)) ∈ [-1, 1].
                        1=정면, 0=edge-on(grazing), <0=면이 카메라를 등짐. 면 선택에는 쓰지 않고
                        가시성(σ 스케일링)·grazing 게이트 입력으로만 쓴다. cam_pos None 이면 둘 다 nan.

    반환
        perm : 길이 8 정수 배열. perm[id] = 입력 corner 인덱스.
               즉 corners_world[perm[k]] 가 새 ID k 의 3D 코너.

    ID 규칙
        FRONT(카메라에 가장 가까운/잘 보이는 side 면)={0,1,2,3}, REAR={4,5,6,7}
        TOP(z 큰)={0,1,5,4}, BOTTOM={3,2,6,7}
        0=front-top-LEFT  1=front-top-RIGHT  2=front-bot-RIGHT  3=front-bot-LEFT
        4=rear-top-LEFT   5=rear-top-RIGHT   6=rear-bot-RIGHT   7=rear-bot-LEFT
    좌/우 는 이미지 x (작을수록 LEFT).
    """
    C = np.asarray(corners_world, dtype=np.float64)
    UV = np.asarray(uv8, dtype=np.float64)

    # 1) top4 / bot4 (world z height)
    z = C[:, 2]
    order_z = np.argsort(z)
    bot4 = list(order_z[:4])
    top4 = list(order_z[4:])

    # 2) vertical pairing: 각 top vertex <-> xy 거리 최소 bot vertex
    pair_bot = {}
    used = set()
    for t in top4:
        best, bestd = None, 1e18
        for b in bot4:
            if b in used:
                continue
            d = np.hypot(C[t, 0] - C[b, 0], C[t, 1] - C[b, 1])
            if d < bestd:
                bestd, best = d, b
        pair_bot[t] = best
        used.add(best)

    # 3-4) 4개 side 면을 모두 후보로 두고, outward normal 의 "방위각"이 (파렛트 중심->카메라)
    #    방향 방위각 φ_cam 과 가장 가까운 면 = FRONT (azimuth rule, 2026-07-24 승인).
    #    [설계 근거] 옛 normal-facing(3D dot 최대) 규칙은 고앙각에서 FRONT 면이 grazing 이 되어
    #    front_cos<0.40 게이트로 자동 기각됐다(고앙각에서 판정 불가 → 게이트 완화 필요). 방위각
    #    규칙은 앙각(카메라 높이)과 무관하게 XY평면 방위만으로 4옆면 중 카메라를 마주보는 면을
    #    고르므로, 고앙각에서도 게이트 완화 없이 FRONT 를 안정적으로 판정한다.
    #    [BUGFIX 2026-07-03 유지] top4 를 "평행 opposite-edge 쌍 1개" 로만 split 하면 직사각 top
    #    face 의 두 평행쌍(±W, ±D)이 |cos|=1 로 동률이라 FRONT 후보가 한 축쌍에 갇혔다. 해결책은
    #    동일: top4 를 centroid(xy) 방위각으로 정렬해 4개 top-edge(=4개 옆면)를 만들고 네 옆면을
    #    모두 후보로 둔다. FRONT 의 맞은편(+2)이 REAR.
    #    [전제] 파렛트 접지(roll·pitch≈0)라 side 면 outward normal 이 (거의) 수평 → XY 방위각이
    #    well-defined. 적재/포크 파렛트(기울어짐)로 일반화할 때는 φ_cam·φ_face 를 파렛트 up벡터
    #    평면에 투영해 정의해야 한다(현재 미구현, 접지 가정).
    def face_quad(top_edge):
        # top_edge 두 정점 + 그 vertical 짝(bot) => 4점, 사각형 순회 순서
        t0, t1 = top_edge
        return [t0, t1, pair_bot[t1], pair_bot[t0]]

    cen_xy = C[:, :2].mean(axis=0)
    top_cyc = sorted(top4, key=lambda t: np.arctan2(C[t, 1] - cen_xy[1],
                                                    C[t, 0] - cen_xy[0]))
    top_edges = [(top_cyc[i], top_cyc[(i + 1) % 4]) for i in range(4)]

    centroid = C.mean(axis=0)
    facing_margin = float("nan")
    front_cos = float("nan")
    if cam_pos is not None:
        cam = np.asarray(cam_pos, dtype=np.float64)
        # φ_cam: 파렛트 중심 -> 카메라 방향을 월드 XY평면에 투영한 방위각(도).
        phi_cam = float(np.degrees(np.arctan2(cam[1] - centroid[1],
                                              cam[0] - centroid[0])))
        face_normals, dphi = [], []
        for te in top_edges:
            n = _face_outward_normal(C[face_quad(te)], centroid)
            face_normals.append(n)
            # φ_face: 옆면 outward normal 의 XY 방위각(도). Δφ = φ_cam - φ_face 를 (-180,180] wrap.
            phi_face = float(np.degrees(np.arctan2(n[1], n[0])))
            dphi.append(_wrap_deg(phi_cam - phi_face))
        front_i = int(np.argmin([abs(d) for d in dphi]))
        # facing_margin (도): 45 - |Δφ_front|. 4옆면 normal 방위각은 ~90° 간격이라 최근접 면의
        #   |Δφ|∈[0,45]; 45=정면, 0=코너온(인접 두 면 애매). ★ 단위가 cos 차이가 아니라 도(deg).
        facing_margin = float(45.0 - abs(dphi[front_i]))
        # front_cos: FRONT(방위각으로 선택된 면)의 3D facing cos = 카메라 정면도. 면 선택에는 쓰지
        #   않고, 가시성(σ 스케일링)·grazing 게이트 입력으로만 남긴다.
        v = cam - C[face_quad(top_edges[front_i])].mean(axis=0)
        nv = np.linalg.norm(v)
        front_cos = float(np.dot(face_normals[front_i], v / nv)) if nv > 1e-9 else -1.0
    else:
        # cam_pos 없으면 2D 투영면적 최대 면 = FRONT (큰 면 가정 fallback).
        front_i = int(np.argmax([_polyarea_2d(UV[face_quad(te)]) for te in top_edges]))

    front_top_edge = top_edges[front_i]
    rear_top_edge = top_edges[(front_i + 2) % 4]

    # 5) FRONT-TOP edge 에서 image x 작은 쪽=0(좌), 큰 쪽=1(우)
    ft0, ft1 = front_top_edge
    if UV[ft0, 0] <= UV[ft1, 0]:
        id0, id1 = ft0, ft1
    else:
        id0, id1 = ft1, ft0

    # 6) front-bot: vertical pairing (3=below 0(left), 2=below 1(right))
    id3 = pair_bot[id0]
    id2 = pair_bot[id1]

    # 7) rear: connector edges are 0-4,1-5,2-6,3-7 by CONVENTION, i.e. id4 is the
    #    depth partner of id0 (the rear-top vertex directly behind id0 along the
    #    depth axis), id5 the depth partner of id1.  Sorting the rear-top edge by
    #    image-x is WRONG: because the rear face is the far side, its image-left
    #    vertex is the depth partner of the front-RIGHT corner, not the left one
    #    -> connectors cross (X-shaped wireframe).  Pair by 3D proximity instead.
    rt0, rt1 = rear_top_edge
    d0_rt0 = np.linalg.norm(C[id0] - C[rt0])
    d0_rt1 = np.linalg.norm(C[id0] - C[rt1])
    if d0_rt0 <= d0_rt1:
        id4, id5 = rt0, rt1
    else:
        id4, id5 = rt1, rt0
    id7 = pair_bot[id4]
    id6 = pair_bot[id5]

    perm = np.array([id0, id1, id2, id3, id4, id5, id6, id7], dtype=int)
    if return_margin:
        return perm, facing_margin, front_cos
    return perm
