#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""把身体腿部的肤色「烘焙」到丝袜自己的 UV 上 —— 独立丝袜网格的默认肤色来源(skill efmi-sheer-skin 肤色来源 C)。

    python bake_skin_to_stocking_uv.py --ini <mod.ini> --stocking <丝袜资源> --stocking-draw <数量>[,<起点>[,<基顶点>]]
                                       [--stocking <第二片> --stocking-draw <…> …]
                                       --body <身体资源> --body-draw <数量>[,<起点>[,<基顶点>]] --body-tex <身体 diffuse.dds>
                                       --out <输出.dds> [--stocking-tex <丝袜 diffuse.dds>] [--size 2048] [--k 8] [--preview <png>]

为什么要烘焙:独立丝袜网格有自己的一套 UV,替换 PS 画丝袜时拿到的是丝袜 UV,拿它去查身体贴图会查到别的部位,
所以以前只能用一个常数肤色(透出来一整片平色)。这里先做一张「按丝袜 UV 排布的肤色图」,替换 PS 再逐像素采样它。
丝袜自己的 diffuse 不动;透肉仍由着色器按视角实时算,这张图只是「袜子底下是什么颜色」的输入。

参数:
  资源       三种写法都认(按顺序试):
             ① 前缀 <p>:ini 里 [Resource_<p>_Index] / [Resource_<p>_Position] / [Resource_<p>_Texcoord](骨骼合并导出),
             ② 前缀 <p>:[Resource_<p>_IB] / [Resource_<p>_VB0] / [Resource_<p>_VB1](SSMT / LoyalTools 导出,例 Component4),
             ③ 明写三段:ib=<段名>,pos=<段名>,uv=<段名>(段名不带方括号)。
             脚本从这三段读 filename / stride / format(filename 相对 ini 所在目录)。
  --stocking / --stocking-draw  可以成对重复给:几片丝袜(例如左右腿分在两个 Component、或跨 IB 画的那片)烘进同一张图。
             前提是它们采样同一张 diffuse、UV 岛不互相压;脚本会报重叠像素比例和重叠处两片颜色差,差得大就分开烘。
  --*-draw   那个部件「画丝袜」/「画腿」那一行 drawindexed(instanced) 的 数量,起点,基顶点
             (instanced 写法 `数量,INSTANCE_COUNT,起点,基顶点,FIRST_INSTANCE` 取第 1、3、4 个数)。
             身体要选画腿的那一次(身体网格 + 默认身体贴图那次)。
  --body-tex 那次身体 draw 绑的 diffuse(相对 ini 目录或绝对路径);sRGB / UNORM 格式自动识别,按游戏实际读到的值换算。
  --stocking-tex 可选:丝袜自己的 diffuse。给了就在丝袜 UV 岛内取样,打印袜色中位数(sRGB),直接喂 suggest_sheer_params.py --fabric。

做法:
  1. 每个丝袜 UV 像素恢复三角形上的 3D 位置，用 AABB 树查询身体三角形表面的真实最近点；
  2. 按最近点的重心坐标恢复身体 UV，在线性空间双线性采样原分辨率贴图，保留纹理内部变化；
  3. UV 岛外扩 32 像素，生成完整 mip，写出 R8G8B8A8_UNORM_SRGB DDS。
  --batch-pixels 控制查询临时内存；--k 为兼容参数，现控制树叶中最多三角形数，不要求顶点数大于 K。
  同资源不同 draw 合法；同资源同 draw 须确认 --body-tex 是真实光腿贴图并传 --body-tex-is-bare。
  已有光腿贴图且 UV 兼容时优先直接采样；需要重映射时本脚本也支持同几何重采样。
  任一覆盖像素距离超过 --max-distance-mm(默认 10 mm)或重叠肤色冲突时写质量诊断和 mask；修复后继续烘焙，不以常数肤色替代多色来源。
  左右腿共用一套 UV(镜像 / 重复几何)时同一纹素会被两片三角形写入：默认 --uv-twins fail 仍报冲突，但质量 JSON 的 uv_twins 会说明
  冲突是否全部落在 UV 完全重合的三角形上；--uv-twins auto 只烘分离最明显那根世界轴正侧的一侧(x+ … z- 可指定)，另一侧的顶点
  读同一批纹素，两侧的色差写进 uv_twins.other_side 供判定。
假设 Position 前 12 字节为 float3、Texcoord 前 8 字节为 float2。依赖 numpy、Pillow，无新增依赖。
只读源文件，只写 --out 与 --preview。
"""
# 输入为腿部/丝袜 draw、Position/UV 和经确认的光腿 diffuse；输出是按丝袜 UV 重映射的 DDS。
# 输出表面距离中位/P99/最大值（毫米）、覆盖率、重叠色差和岛内肤色中位；错误返回非 0。

import argparse, pathlib, re, struct, sys, json
import numpy as np
from PIL import Image
from texture_colour import load_colour_texture, srgb_to_linear, linear_to_srgb

SRGB_DXGI = {29, 72, 75, 78, 91, 93, 99}

# Section-name suffixes tried for each buffer kind, in order: merged-skeleton export, then SSMT / LoyalTools export.
NAMING = (
    {"Index": "Index", "Position": "Position", "Texcoord": "Texcoord"},
    {"Index": "IB", "Position": "VB0", "Texcoord": "VB1"},
)


# Convert sRGB samples to linear light before interpolation.
def s2l(c):
    return srgb_to_linear(c)


# Convert interpolated linear colours back to sRGB for previews and DDS storage.
def l2s(c):
    return linear_to_srgb(c)


# Decode an INI while preserving compatibility with common UTF and legacy encodings.
def read_text(p):
    b = p.read_bytes()
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", "replace")


# Locate one named INI section without treating similarly prefixed sections as a match.
def section(ini_text, name):
    """Return the key/value dict of one [section], or None when the ini has no such section."""
    m = re.search(r"^\[" + re.escape(name) + r"\][ \t]*\r?$(.*?)(?=^\[|\Z)", ini_text, re.M | re.S | re.I)
    if not m:
        return None
    return {k.strip().lower(): v.strip() for k, v in re.findall(r"^[ \t]*([A-Za-z_0-9]+)[ \t]*=[ \t]*(.+?)[ \t]*\r?$", m.group(1), re.M)}


# Resolve the supported resource naming styles into index, position, and UV section names.
def resources(ini_text, spec):
    """Resolve the index / position / texcoord sections of one mesh from a prefix or an explicit ib=,pos=,uv= triple."""
    if "=" in spec:
        names = dict(kv.split("=", 1) for kv in spec.split(","))
        want = {"Index": names.get("ib"), "Position": names.get("pos"), "Texcoord": names.get("uv")}
        if not all(want.values()):
            sys.exit(f"资源写法 ③ 要三段都给:ib=<段名>,pos=<段名>,uv=<段名>(收到 {spec!r})")
        out = {k: section(ini_text, v) for k, v in want.items()}
        missing = [want[k] for k, v in out.items() if v is None]
        if missing:
            sys.exit(f"ini 里找不到段 {missing}")
        return out
    for naming in NAMING:
        out = {k: section(ini_text, f"Resource_{spec}_{suffix}") for k, suffix in naming.items()}
        if all(v is not None for v in out.values()):
            return out
    sys.exit(f"ini 里既没有 [Resource_{spec}_Index/_Position/_Texcoord] 也没有 [Resource_{spec}_IB/_VB0/_VB1] —— "
             "资源前缀写错了?也可以明写 ib=<段名>,pos=<段名>,uv=<段名>")


# Normalize indexed and indexed-instanced draw arguments to count, start, and base vertex.
def parse_draw(s):
    v = [int(x) for x in s.split(',')]
    if len(v) == 5:
        if v[1] <= 0 or v[4] < 0:
            raise ValueError('draw instance count 必须为正，first instance 不得为负')
        v = [v[0], v[2], v[3]]
    elif 1 <= len(v) <= 3:
        v = (v + [0, 0])[:3]
    else:
        raise ValueError('draw 需 1–3 个参数，或完整 5 参数 instanced 写法')
    if v[0] <= 0 or v[0] % 3 or v[1] < 0:
        raise ValueError('draw 数量必须是正的 3 倍数，起点不得为负；核对原始 draw')
    return v


# Load one bounded mesh slice and reject resource layouts that would make the bake ambiguous.
def load_mesh(ini_dir, res, draw, what):
    n, start, base = draw
    dt = np.uint16 if "R16" in res["Index"].get("format", "").upper() else np.uint32
    index_path = ini_dir / res["Index"]["filename"]
    if index_path.stat().st_size % np.dtype(dt).itemsize:
        raise ValueError(f'{what}:IB 字节数与 format 不匹配；修正索引格式或缓冲后重新烘焙')
    ib = np.fromfile(index_path, dtype=dt).astype(np.int64)
    if n <= 0 or n % 3 or start < 0 or start + n > len(ib):
        sys.exit(f"{what}:起点 + 数量 = {start + n} 超出 IB({len(ib)} 个索引)")
    ib = ib[start:start + n] + base
    ps, ts = int(res["Position"]["stride"]), int(res["Texcoord"]["stride"])
    if ps < 12 or ts < 8:
        raise ValueError(f'{what}:Position stride 至少 12，Texcoord stride 至少 8；核对资源布局')
    pos = np.fromfile(ini_dir / res["Position"]["filename"], dtype=np.uint8).reshape(-1, ps)[:, :12].copy().view(np.float32).reshape(-1, 3)
    uv = np.fromfile(ini_dir / res["Texcoord"]["filename"], dtype=np.uint8).reshape(-1, ts)[:, :8].copy().view(np.float32).reshape(-1, 2)
    if ib.min() < 0 or ib.max() >= min(len(pos), len(uv)):
        sys.exit(f"{what}:顶点号 {ib.max()} 超出顶点缓冲(Position {len(pos)} / Texcoord {len(uv)})")
    v = np.unique(ib)
    if not np.isfinite(pos[v]).all() or not np.isfinite(uv[v]).all():
        raise ValueError(f'{what}:Position/UV 存在 NaN/Inf；修复缓冲布局或源数据后重新烘焙')
    if ((uv[v] < 0) | (uv[v] > 1)).any():
        raise ValueError(f'UV_RANGE: {what}:UV 超出 [0,1]；核对 Texcoord 通道，按原寻址展开 UV 或提供正确映射后重跑')
    return ib, pos.astype(np.float64), uv.astype(np.float64)


# Keep the native resolution so interior texture details survive the bake.
def texture_1024(path, colour_space='auto'):
    """Load the native DDS/PNG resolution; retain the legacy function name for callers."""
    linear, meta = load_colour_texture(path, colour_space)
    srgb = meta['colour_space'] == 'srgb'
    return (l2s(linear) if srgb else linear), srgb


# Sample RGB values continuously so transferred skin colour does not inherit nearest-texel steps.
def bilinear(img, uv):
    h, w = img.shape[:2]
    x = np.clip(uv[:, 0] * w - 0.5, 0, w - 1); y = np.clip(uv[:, 1] * h - 0.5, 0, h - 1)
    x0 = x.astype(int); y0 = y.astype(int); fx = (x - x0)[:, None]; fy = (y - y0)[:, None]
    x1 = np.minimum(x0 + 1, w - 1); y1 = np.minimum(y0 + 1, h - 1)
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x1] * fx * (1 - fy)
            + img[y1, x0] * (1 - fx) * fy + img[y1, x1] * fx * fy)


# Write the generated mip chain as an sRGB DDS accepted by the runtime.
def write_dds(path, mips):
    h, w = mips[0].shape[:2]
    hdr = struct.pack("<4sIIIIIII44s", b"DDS ", 124, 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | 0x20000, h, w, w * 4, 0, len(mips), b"\0" * 44)
    hdr += struct.pack("<II4sIIIII", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
    hdr += struct.pack("<IIIII", 0x401008, 0, 0, 0, 0)
    hdr += struct.pack("<IIIII", 29, 3, 0, 1, 0)       # DXGI_FORMAT_R8G8B8A8_UNORM_SRGB, TEXTURE2D
    with open(path, "wb") as f:
        f.write(hdr)
        for m in mips:
            f.write(np.ascontiguousarray(m, dtype=np.uint8).tobytes())


# Find the closest point on each triangle, including its edges and vertices.
def closest_triangles(points, triangles):
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    ab, ac = b - a, c - a
    normal = np.cross(ab, ac)
    norm2 = (normal * normal).sum(1)
    offset = points[:, None] - a[None]
    projected = points[:, None] - (((offset * normal).sum(2) / norm2)[..., None] * normal)
    v = projected - a
    aa = (ab * ab).sum(1); bb = (ab * ac).sum(1); cc = (ac * ac).sum(1)
    av = (v * ab).sum(2); cv = (v * ac).sum(2)
    determinant = aa * cc - bb * bb
    u = (cc * av - bb * cv) / determinant
    w = (aa * cv - bb * av) / determinant
    bary = np.stack([1 - u - w, u, w], axis=2)
    inside = (bary >= 0).all(2)
    distance = ((points[:, None] - projected) ** 2).sum(2)
    distance[~inside] = np.inf
    for start, end in ((0, 1), (1, 2), (2, 0)):
        origin = triangles[:, start]; edge = triangles[:, end] - origin
        t = np.clip(((points[:, None] - origin) * edge).sum(2) / (edge * edge).sum(1), 0, 1)
        q = origin + t[..., None] * edge
        d = ((points[:, None] - q) ** 2).sum(2)
        replace = d < distance
        edge_bary = np.zeros_like(bary)
        edge_bary[..., start] = 1 - t; edge_bary[..., end] = t
        bary[replace] = edge_bary[replace]; distance[replace] = d[replace]
    nearest = distance.argmin(1)
    rows = np.arange(len(points))
    return distance[rows, nearest], nearest, bary[rows, nearest]


# A median-split AABB hierarchy gives exact surface queries without a new dependency.
class TriangleSurface:
    def __init__(self, triangles, uv, leaf_size=8):
        if not np.isfinite(triangles).all() or not np.isfinite(uv).all():
            raise ValueError('身体 Position/UV 存在 NaN/Inf；修复缓冲布局或源数据后重新烘焙')
        normal = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        valid = (normal * normal).sum(1) > 1e-24
        self.triangles = triangles[valid]; self.uv = uv[valid]
        if not len(self.triangles):
            raise ValueError('身体 draw 没有有效三角形；重新选择腿部 draw 后烘焙')
        lo = self.triangles.min(1); hi = self.triangles.max(1)
        centers = (lo + hi) * .5
        self.nodes = []

        # Partition by the widest centroid axis to keep the traversal balanced.
        def build(ids):
            index = len(self.nodes)
            self.nodes.append(None)
            lower, upper = lo[ids].min(0), hi[ids].max(0)
            if len(ids) <= max(1, leaf_size):
                self.nodes[index] = (lower, upper, ids, None, None)
            else:
                axis = np.ptp(centers[ids], axis=0).argmax()
                ids = ids[np.argsort(centers[ids, axis], kind='stable')]
                middle = len(ids) // 2
                left, right = build(ids[:middle]), build(ids[middle:])
                self.nodes[index] = (lower, upper, None, left, right)
            return index
        build(np.arange(len(self.triangles)))

    # Prune only boxes farther than the best exact point found so far.
    def sample(self, points):
        if not np.isfinite(points).all():
            raise ValueError('丝袜 Position 存在 NaN/Inf；修复布局后重新烘焙')
        best = np.full(len(points), np.inf); result = np.zeros((len(points), 2))
        stack = [(0, np.arange(len(points)))]
        while stack:
            node, rows = stack.pop()
            lower, upper, ids, left, right = self.nodes[node]
            delta = np.maximum(np.maximum(lower - points[rows], points[rows] - upper), 0)
            rows = rows[(delta * delta).sum(1) <= best[rows]]
            if not len(rows):
                continue
            if ids is not None:
                distance, nearest, bary = closest_triangles(points[rows], self.triangles[ids])
                replace = distance < best[rows]
                selected = rows[replace]
                best[selected] = distance[replace]
                result[selected] = (self.uv[ids[nearest[replace]]] * bary[replace, :, None]).sum(1)
            else:
                # Visit the near child first for each query; tighter bounds reduce later work.
                center_left = (self.nodes[left][0] + self.nodes[left][1]) * .5
                center_right = (self.nodes[right][0] + self.nodes[right][1]) * .5
                near_left = ((points[rows] - center_left) ** 2).sum(1) <= ((points[rows] - center_right) ** 2).sum(1)
                lr, rr = rows[near_left], rows[~near_left]
                if len(lr):
                    stack.append((right, lr))
                if len(rr):
                    stack.append((left, rr))
                    stack.append((right, rr))
                if len(lr):
                    stack.append((left, lr))
        return np.sqrt(best), result


# Quality failures carry pixel masks so the CLI can locate the repair before exiting.
class BakeQualityError(ValueError):
    def __init__(self, code, message, report, mask):
        super().__init__(f'{code}: {message}')
        self.report = dict(report, status='failed', code=code, recovery=message)
        self.mask = mask


def _raster_batches(sib, suv, size, batch_pixels=65536):
    """Yield covered texels using at most batch_pixels candidate pixels at once."""
    if size < 1 or not 1 <= batch_pixels <= 65536:
        raise ValueError('RASTER_BUDGET: size must be positive; batch_pixels must be 1..65536')
    tri = np.asarray(sib).reshape(-1, 3)
    used_uv = np.asarray(suv)[tri]
    if not np.isfinite(used_uv).all() or (used_uv < 0).any() or (used_uv > 1).any():
        raise ValueError('UV_RANGE: UV must be finite within [0,1]; unfold the original address mapping or correct the UV channel, then rerun')
    for triangle_id, indices in enumerate(tri):
        p = suv[indices] * size
        a, b, c = p
        denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(denominator) <= 1e-12:
            continue
        lower = np.clip(np.floor(p.min(0)).astype(int), 0, size - 1)
        upper = np.clip(np.ceil(p.max(0)).astype(int), 0, size - 1)
        width = upper[0] - lower[0] + 1
        total = width * (upper[1] - lower[1] + 1)
        for start in range(0, total, batch_pixels):
            offset = np.arange(start, min(start + batch_pixels, total))
            x = lower[0] + offset % width; y = lower[1] + offset // width
            u = ((b[1] - c[1]) * (x + .5 - c[0]) + (c[0] - b[0]) * (y + .5 - c[1])) / denominator
            v = ((c[1] - a[1]) * (x + .5 - c[0]) + (a[0] - c[0]) * (y + .5 - c[1])) / denominator
            bary = np.stack([u, v, 1 - u - v], axis=1)
            inside = (bary >= -1e-6).all(1)
            if inside.any():
                yield triangle_id, indices, y[inside] * size + x[inside], bary[inside]


def _pixel_locations(flat, size, limit=32):
    """Keep a readable location sample; the companion mask retains every error pixel."""
    return [[int(i % size), int(i // size)] for i in flat[:limit]]


def bake_surface(sib, spos, suv, surface, texture, size, batch_pixels, what,
                 max_distance_mm=10., quality=None):
    """Sample real body colour and reject any distance or UV colour conflict."""
    if not np.isfinite(max_distance_mm) or max_distance_mm <= 0:
        raise ValueError('DISTANCE_ARGUMENT: --max-distance-mm must be finite and positive')
    acc = np.zeros((size * size, 3)); count = np.zeros(size * size)
    distances = np.full(size * size, np.nan)
    owners = np.full(size * size, -1, dtype=np.int32)
    report = dict(piece=what, max_distance_mm=float(max_distance_mm), address_mode='clamp',
                  batch_pixels=batch_pixels, overlap_pixels=0, conflict_pixels=0)
    for triangle_id, indices, flat, bary in _raster_batches(sib, suv, size, batch_pixels):
        distance, body_uv = surface.sample(bary @ spos[indices])
        if not np.isfinite(distance).all() or not np.isfinite(body_uv).all():
            raise ValueError('SURFACE_INVALID: body surface produced nonfinite samples; correct the source mesh then rerun')
        if (body_uv < -1e-9).any() or (body_uv > 1 + 1e-9).any():
            raise ValueError('UV_RANGE: body sample lies outside [0,1]; unfold its original addressing before baking')
        colour = bilinear(texture, body_uv)
        overlap = count[flat] > 0
        report['overlap_pixels'] += int(overlap.sum())
        if overlap.any():
            old = acc[flat[overlap]] / count[flat[overlap], None]
            conflict = np.max(np.abs(old - colour[overlap]), axis=1) > 1e-5
            if conflict.any():
                ids = flat[overlap][conflict]
                mask = np.zeros(size * size, dtype=bool); mask[ids] = True
                report.update(conflict_pixels=int(conflict.sum()), locations_xy=_pixel_locations(ids, size),
                              previous_triangles=sorted(set(int(i) for i in owners[ids])), triangle=int(triangle_id),
                              coverage_complete=False)
                raise BakeQualityError('UV_COLOUR_CONFLICT',
                    f'{what}:重叠 UV 对应不同肤色；按报告三角形拆成独立 DDS 并分别接线，或修 UV 后重跑',
                    report, mask.reshape(size, size))
        np.add.at(acc, flat, colour); np.add.at(count, flat, 1)
        replace = np.isnan(distances[flat]) | (distance > distances[flat])
        distances[flat[replace]] = distance[replace]; owners[flat[replace]] = triangle_id
    filled = count > 0
    if not filled.any():
        raise ValueError(f'UV_EMPTY: {what}:UV 无覆盖像素；检查 UV 通道、draw 和输出分辨率后重新烘焙')
    d = distances[filled] * 1000
    report.update(coverage_pixels=int(filled.sum()), coverage_complete=True,
                  distance_mm=dict(median=float(np.median(d)), p99=float(np.percentile(d, 99)), maximum=float(d.max())))
    worst = int(np.nanargmax(distances))
    report['worst'] = dict(x=worst % size, y=worst // size, triangle=int(owners[worst]))
    exceeded = filled & (distances * 1000 > max_distance_mm + .001)
    report['distance_exceeded_pixels'] = int(exceeded.sum())
    print(f'{what}:surface distance mm median={np.median(d):.3f}, P99={np.percentile(d, 99):.3f}, max={d.max():.3f}')
    if exceeded.any():
        report['locations_xy'] = _pixel_locations(np.flatnonzero(exceeded), size)
        raise BakeQualityError('DISTANCE_LIMIT',
            f'{what}:存在覆盖像素距离超过 {max_distance_mm:g} mm；按 mask 和 triangle 核对身体 draw、坐标布局或配准后重跑；仅有真实几何间隙证据才调整阈值',
            report, exceeded.reshape(size, size))
    report['status'] = 'passed'
    if quality is not None:
        quality.update(report)
    return acc, count


def merge_baked_pieces(pieces, size):
    """Merge only agreeing overlaps; different skin colours require separate DDS files."""
    acc = np.zeros((size * size, 3)); count = np.zeros(size * size)
    for index, (colours, hits) in enumerate(pieces):
        both = (count > 0) & (hits > 0)
        if both.any():
            ids = np.flatnonzero(both)
            difference = np.max(np.abs(acc[ids] / count[ids, None] - colours[ids] / hits[ids, None]), axis=1)
            bad = ids[difference > 1e-5]
            if len(bad):
                mask = np.zeros(size * size, dtype=bool); mask[bad] = True
                raise BakeQualityError('CROSS_PIECE_UV_CONFLICT',
                    f'第 {index + 1} 片与前片肤色冲突；分别烘成独立 DDS 并按对应 draw 接线，或修 UV 后重跑',
                    dict(piece=index + 1, conflict_pixels=len(bad), locations_xy=_pixel_locations(bad, size)), mask.reshape(size, size))
        acc += colours; count += hits
    return acc, count


def rasterize(sib, suv, vcol, S, batch_pixels=65536):
    """Keep the preview API while bounding candidate expansion independently of triangle count."""
    acc = np.zeros((S * S, 3)); count = np.zeros(S * S)
    for _, indices, flat, bary in _raster_batches(sib, suv, S, batch_pixels):
        np.add.at(acc, flat, bary @ vcol[indices]); np.add.at(count, flat, 1)
    return acc, count


def dilate_colour(img, filled, iterations=32):
    """Pad UV islands without wrapping one texture border onto the opposite side."""
    img = img.copy(); filled = filled.copy()
    mean = img[filled].mean(0)
    for _ in range(iterations):
        colours = np.zeros_like(img); count = np.zeros(img.shape[:2])
        active = img * filled[..., None]
        colours[1:] += active[:-1]; count[1:] += filled[:-1]
        colours[:-1] += active[1:]; count[:-1] += filled[1:]
        colours[:, 1:] += active[:, :-1]; count[:, 1:] += filled[:, :-1]
        colours[:, :-1] += active[:, 1:]; count[:, :-1] += filled[:, 1:]
        grow = (~filled) & (count > 0)
        img[grow] = colours[grow] / count[grow, None]; filled |= grow
    img[~filled] = mean
    return img


UV_TWIN_POLICIES = ('fail', 'auto', 'x+', 'x-', 'y+', 'y-', 'z+', 'z-')


def find_uv_twins(sib, suv, size):
    """Group triangles whose three UV corners coincide at the bake resolution.

    Mirrored legs commonly share one UV island, so each texel receives triangles from two
    different 3D places. Corners are quantised to a quarter texel of the requested size,
    which groups bit-identical layouts without an absolute UV tolerance.
    """
    tri = np.asarray(sib).reshape(-1, 3)
    corners = np.round(np.asarray(suv)[tri] * size * 4).astype(np.int64)
    groups = {}
    for triangle_id, corner in enumerate(corners):
        groups.setdefault(tuple(sorted(map(tuple, corner))), []).append(triangle_id)
    return [members for members in groups.values() if len(members) > 1]


def choose_twin_side(groups, spos, sib, policy):
    """Keep one triangle per twin group on the side named by `policy`.

    `auto` keeps the positive side of the world axis along which the groups spread most;
    `x+` … `z-` name axis and sign directly. Returns the kept index list, the keep mask and
    the evidence a reader needs to judge the choice.
    """
    tri = np.asarray(sib).reshape(-1, 3)
    centroids = np.asarray(spos)[tri].mean(1)
    spread = np.array([np.ptp(centroids[members], axis=0) for members in groups])
    if policy == 'auto':
        axis, sign = int(np.argmax(spread.mean(0))), 1
    else:
        axis, sign = 'xyz'.index(policy[0]), 1 if policy[1] == '+' else -1
    keep = np.ones(len(tri), dtype=bool)
    for members in groups:
        ranked = sorted(members, key=lambda t: sign * centroids[t, axis])
        keep[ranked[:-1]] = False
    info = dict(axis='xyz'[axis], side='+' if sign > 0 else '-', dropped_triangles=int((~keep).sum()),
                separation_mm=dict(median=float(np.median(spread[:, axis]) * 1000),
                                   maximum=float(spread[:, axis].max() * 1000)))
    return tri[keep].reshape(-1), keep, info


def twin_texels(groups, sib, suv, size, batch_pixels):
    """Texels covered by any triangle that has a UV twin."""
    tri = np.asarray(sib).reshape(-1, 3)
    members = [t for group in groups for t in group]
    covered = np.zeros(size * size, dtype=bool)
    for _, _, flat, _ in _raster_batches(tri[members].reshape(-1), suv, size, batch_pixels):
        covered[flat] = True
    return covered


def other_side_difference(dropped, spos, suv, surface, texture, acc, count, size, batch_pixels):
    """Sample the dropped twins and report how far they differ from the baked side, in sRGB levels."""
    levels, marked = [], []
    for _, indices, flat, bary in _raster_batches(dropped, suv, size, batch_pixels):
        _, body_uv = surface.sample(bary @ spos[indices])
        colour = bilinear(texture, body_uv)
        have = count[flat] > 0
        kept = acc[flat[have]] / count[flat[have], None]
        diff = np.abs(l2s(kept) - l2s(colour[have])).max(1) * 255
        levels.append(diff)
        marked.append(flat[have][diff > 16])
    diff = np.concatenate(levels) if levels else np.zeros(0)
    marked = np.concatenate(marked) if marked else np.zeros(0, dtype=int)
    box = None
    if len(marked):
        x, y = marked % size, marked // size
        box = [int(x.min()), int(y.min()), int(x.max()), int(y.max())]
    return dict(pixels=int(diff.size), over_4_levels=int((diff > 4).sum()), over_16_levels=int((diff > 16).sum()),
                max_levels=float(diff.max()) if diff.size else 0.0, over_16_box_xy=box)


# Validate all pieces, merge their rasterized colours, build mips, and write the requested artifacts.
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ini", required=True)
    ap.add_argument("--stocking", required=True, action="append", help="丝袜资源(前缀或 ib=,pos=,uv= 三段);可重复,几片烘进一张")
    ap.add_argument("--stocking-draw", required=True, action="append", help="数量[,起点[,基顶点]];与 --stocking 一一对应")
    ap.add_argument("--body", required=True, help="身体资源(前缀或 ib=,pos=,uv= 三段)")
    ap.add_argument("--body-draw", required=True, help="数量[,起点[,基顶点]](画腿那一次)")
    ap.add_argument("--body-tex", required=True, help="那次身体 draw 的 diffuse")
    ap.add_argument('--colour-space', choices=('auto', 'srgb', 'linear'), default='auto', help='身体/可选袜图的颜色空间；auto 按明确格式，旧 DDS 须核对原 SRV 后显式指定')
    ap.add_argument('--body-tint-linear', default='1,1,1', help='真实身体固定线性 RGB 乘数；默认 1,1,1 必须先证明无额外染色，动态染色需现场映射')
    ap.add_argument('--max-distance-mm', type=float, default=10., help='所有覆盖像素的最大身体距离，默认 10 mm；调整须记录几何证据')
    ap.add_argument('--quality-json', help='质量 JSON；不填写为输出名.quality.json，失败写定位 mask，不写 DDS')
    ap.add_argument("--stocking-tex", default=None, help="可选:丝袜自己的 diffuse,岛内取样打印袜色中位数(喂 suggest_sheer_params.py --fabric)")
    ap.add_argument("--out", required=True, help="输出 DDS(一般放 mod 的 Textures 里)")
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--k", type=int, default=8, help="AABB 树叶最多三角形数，兼容旧参数")
    ap.add_argument("--batch-pixels", type=int, default=4096, help="每批最多查询的目标像素，降低可节省临时内存")
    ap.add_argument("--body-tex-is-bare", action="store_true", help="同资源同 draw 时确认输入贴图来自真实光腿状态")
    ap.add_argument('--uv-twins', choices=UV_TWIN_POLICIES, default='fail',
                    help='UV 完全重合的三角形(镜像/重复几何)怎么处理：fail 报冲突并诊断；auto 只烘分离最明显轴的正侧；x+ … z- 指定轴和侧')
    ap.add_argument("--preview", default=None, help="出一张 1024 预览 PNG(暗处 = UV 岛以外)")
    a = ap.parse_args()
    quality_path = pathlib.Path(a.quality_json) if a.quality_json else pathlib.Path(a.out).with_suffix('.quality.json')
    try:
        report = _run_bake(a)
    except (ValueError, OSError, KeyError, SystemExit) as exc:
        report = dict(schema_version=1, status='failed', output_written=False,
                      code='BAKE_INPUT_INVALID', recovery=str(exc))
        if isinstance(exc, BakeQualityError):
            report.update(exc.report)
            mask_path = quality_path.with_suffix('.mask.png')
            mask_path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(exc.mask.astype(np.uint8) * 255).save(mask_path)
            report['error_mask'] = str(mask_path.resolve())
        quality_path.parent.mkdir(parents=True, exist_ok=True)
        quality_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        raise ValueError(f'{exc}; inspect {quality_path} then rerun the same command after repair') from exc
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def _run_bake(a):
    """Validate colour and spatial inputs before writing the final DDS."""
    if len(a.stocking) != len(a.stocking_draw):
        sys.exit(f"--stocking 给了 {len(a.stocking)} 个,--stocking-draw 给了 {len(a.stocking_draw)} 个,要一一对应")
    if a.size < 1 or a.size & (a.size - 1):
        raise ValueError('--size 必须是正的 2 的幂，以生成完整 mip')
    if not 1 <= a.k <= 64 or not 1 <= a.batch_pixels <= 65536:
        raise ValueError('--k 必须在 1–64，--batch-pixels 必须在 1–65536')
    ini = pathlib.Path(a.ini); d = ini.parent; S = a.size
    text = read_text(ini)
    bib, bpos, buv = load_mesh(d, resources(text, a.body), parse_draw(a.body_draw), "身体")
    bv = np.unique(bib)
    tp = pathlib.Path(a.body_tex); tp = tp if tp.is_absolute() else d / tp
    tex, texture_meta = load_colour_texture(tp, a.colour_space)
    tint = np.asarray([float(value) for value in a.body_tint_linear.split(',')])
    if tint.shape != (3,) or not np.isfinite(tint).all() or (tint < 0).any():
        raise ValueError('BODY_TINT_INVALID: --body-tint-linear requires three finite nonnegative values from the bare-leg colour chain')
    tex *= tint
    if not np.isfinite(tex).all() or (tex > 1).any():
        raise ValueError('BODY_TINT_RANGE: tinted source exceeds RGB8 linear range; capture a bounded colour source or use a verified HDR mapping before baking')
    print(f"身体 draw 顶点 {len(bv)};colour space {texture_meta['colour_space']}; body tint linear {tint.tolist()} (default is 1,1,1; verify the real colour chain)")
    report = dict(schema_version=1, status='passed', output_written=False, body_texture=texture_meta,
                  body_tint_linear=tint.tolist(), max_distance_mm=a.max_distance_mm, pieces=[])

    # One (acc, cnt) pair per stocking piece so overlaps between pieces can be measured before merging.
    pieces = []
    bres = resources(text, a.body)
    surface = TriangleSurface(bpos[bib.reshape(-1, 3)], buv[bib.reshape(-1, 3)], a.k)
    for spec, draw in zip(a.stocking, a.stocking_draw):
        what = f"丝袜[{spec}]"
        sres = resources(text, spec)
        # Identical buffers can contain different draw slices; bare variants can reuse the entire geometry.
        same_slice = sres == bres and parse_draw(draw) == parse_draw(a.body_draw)
        if same_slice and not a.body_tex_is_bare:
            raise ValueError(f'{what}:同资源同 draw；先核对 --body-tex 来自光腿状态，再加 --body-tex-is-bare 重新烘焙')
        sib, spos, suv = load_mesh(d, sres, parse_draw(draw), what)
        piece_quality = {}
        # Triangles that share one UV footprint (mirrored legs) cannot both own a texel.
        groups = find_uv_twins(sib, suv, S)
        twins = dict(policy=a.uv_twins, groups=len(groups), triangles=int(sum(len(g) for g in groups)),
                     total_triangles=len(sib) // 3)
        baked_ib, dropped = sib, np.zeros(0, dtype=np.int64)
        if groups and a.uv_twins != 'fail':
            baked_ib, keep, choice = choose_twin_side(groups, spos, sib, a.uv_twins)
            dropped = np.asarray(sib).reshape(-1, 3)[~keep].reshape(-1)
            twins.update(choice)
            print(f"{what}:UV 重合三角形 {twins['triangles']} 个({len(groups)} 组)，只烘 {choice['axis']}{choice['side']} 一侧，"
                  f"丢弃 {choice['dropped_triangles']} 个；组内分离中位 {choice['separation_mm']['median']:.1f} mm")
        try:
            colours, hits = bake_surface(baked_ib, spos, suv, surface, tex, S, a.batch_pixels, what,
                                         max_distance_mm=a.max_distance_mm, quality=piece_quality)
        except BakeQualityError as exc:
            if exc.report.get('code') == 'UV_COLOUR_CONFLICT' and groups:
                covered = twin_texels(groups, sib, suv, S, a.batch_pixels)
                conflicts = np.flatnonzero(exc.mask.reshape(-1))
                twins.update(conflict_pixels=int(len(conflicts)), conflicts_in_twin_pixels=int(covered[conflicts].sum()))
                if twins['conflicts_in_twin_pixels'] == len(conflicts):
                    exc = BakeQualityError('UV_COLOUR_CONFLICT', exc.report['recovery'] +
                                           '；冲突全部落在 UV 完全重合的三角形上(镜像/重复几何)，用 --uv-twins auto 只烘一侧后重跑同一命令',
                                           exc.report, exc.mask)
            exc.report['uv_twins'] = twins
            raise exc
        if len(dropped):
            twins['other_side'] = other_side_difference(dropped, spos, suv, surface, tex, colours, hits, S, a.batch_pixels)
            other = twins['other_side']
            print(f"{what}:未烘那一侧与烘焙结果的 sRGB 级差：>4 级 {other['over_4_levels']} 像素，>16 级 {other['over_16_levels']} 像素，"
                  f"最大 {other['max_levels']:.0f}；>16 级像素框 {other['over_16_box_xy']}")
        piece_quality['uv_twins'] = twins
        pieces.append((colours, hits))
        report['pieces'].append(piece_quality)
    acc, cnt = merge_baked_pieces(pieces, S)
    filled = cnt > 0
    img = np.zeros((S * S, 3)); img[filled] = acc[filled] / cnt[filled][:, None]
    img = img.reshape(S, S, 3); filled = filled.reshape(S, S)
    print(f"覆盖像素 {filled.mean() * 100:.1f}%(丝袜 UV 岛)")
    img = dilate_colour(img, filled)

    mips, cur = [], img
    while True:
        rgb = np.round(l2s(cur) * 255).astype(np.uint8)
        mips.append(np.dstack([rgb, np.full(rgb.shape[:2], 255, np.uint8)]))
        if cur.shape[0] == 1:
            break
        cur = cur.reshape(cur.shape[0] // 2, 2, cur.shape[1] // 2, 2, 3).mean((1, 3))
    medc = np.median(np.round(l2s(img[filled]) * 255), 0).astype(int)
    print(f"写出 {a.out}:{S}x{S}、{len(mips)} 级 mip;岛内肤色中位 sRGB {medc}(线性 {np.round(s2l(medc / 255), 4)})")
    if a.stocking_tex:
        # Fabric colour = the stocking's own diffuse sampled at the same island texels, for suggest_sheer_params.py --fabric.
        sp = pathlib.Path(a.stocking_tex); sp = sp if sp.is_absolute() else d / sp
        stex, _ = load_colour_texture(sp, a.colour_space)
        py, px = np.nonzero(filled)
        fab = bilinear(stex, np.stack([(px + 0.5) / S, (py + 0.5) / S], 1))
        fab_srgb = l2s(fab)
        medf = np.median(np.round(fab_srgb * 255), 0).astype(int)
        print(f"岛内袜色中位 sRGB {medf}(来自 {sp.name},linear sampling)")
    write_dds(a.out, mips)
    report['output_written'] = True
    if a.preview:
        pv = mips[0][..., :3].copy(); pv[~filled] = (pv[~filled] * 0.35).astype(np.uint8)
        Image.fromarray(pv).resize((1024, 1024), Image.BOX).save(a.preview)
        print(f"预览 {a.preview}(暗处 = 丝袜 UV 岛以外,只是外扩填充)")
    return report


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        sys.exit(f'烘焙输入或资源错误：{exc}；修复输入后重新烘焙')
