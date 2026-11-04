#!/usr/bin/env python3
"""重绑 + 重烘黑龙动画：读 models/dragon-anim.glb，写回 models/dragon-anim.glb 与 models/dragon-anim.b64。

原绑定的三处硬伤（tools/rigdiag.py 实测）：
 1) root 半径 0.30，是骨间距的 3~5 倍，近身骨骼全被它压制 -> 每根肢体只跟随自家骨骼
    60~80%（后腿只有 0.42），翅膀扇动只剩 2/3 幅度，整条龙动起来像橡皮。
 2) 翼尖骨 wingL2/wingR2 的线段退化成一点、且与 wingL1 的末端重合，翼膜权重被两根骨
    平分 -> 扇翼时翼膜被撕开（最大拉伸 100 倍）。
 3) 没有下颌骨：咬、吐息、咆哮一律闭嘴；而 bite 片段里嘴是不会张的，攻击完全读不出来。

本脚本：胶囊距离权重（各向异性 + 分区闸门 + 边上平滑 + top4 归一化）、新增 jaw 骨、
把攻击片段重排成「预备 -> 出招 -> 收招」并在咬/吐/吼/死里张嘴。几何、UV、贴图原样保留。
用法: python models/dragon_rerig.py [--smooth 2]
"""
import struct, json, math, base64, array, argparse, sys
import numpy as np

SRC = 'models/dragon-anim.glb'
DST = 'models/dragon-anim.glb'
B64 = 'models/dragon-anim.b64'

# ---------- 读 GLB（与 tools/rigview.py 的解析保持一致） ----------
CT = {5120: ("i1", 1), 5121: ("u1", 1), 5122: ("i2", 2), 5123: ("u2", 2), 5125: ("u4", 4), 5126: ("f4", 4)}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def parse_glb(path):
    d = open(path, 'rb').read()
    jlen = struct.unpack('<I', d[12:16])[0]
    return json.loads(d[20:20 + jlen]), d, 20 + jlen + 8


def read_acc(g, d, off, ai):
    a = g['accessors'][ai]
    bv = g['bufferViews'][a['bufferView']]
    dt, sz = CT[a['componentType']]
    nc = NC[a['type']]
    base = off + bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    stride = bv.get('byteStride') or sz * nc
    if stride == sz * nc:
        return np.frombuffer(d, dtype=dt, count=a['count'] * nc, offset=base).reshape(a['count'], nc).astype(np.float64)
    out = np.empty((a['count'], nc), dtype=np.float64)
    for i in range(a['count']):
        out[i] = np.frombuffer(d, dtype=dt, count=nc, offset=base + i * stride)
    return out


g, d, off = parse_glb(SRC)
prim = g['meshes'][0]['primitives'][0]
P = read_acc(g, d, off, prim['attributes']['POSITION'])
N = read_acc(g, d, off, prim['attributes']['NORMAL'])
UV = read_acc(g, d, off, prim['attributes']['TEXCOORD_0'])
IDX = read_acc(g, d, off, prim['indices']).astype(np.int64).ravel()
NV = len(P)
img_bytes = []
for im in g['images']:
    bv = g['bufferViews'][im['bufferView']]
    o = off + bv.get('byteOffset', 0)
    img_bytes.append(d[o:o + bv['byteLength']])
print('源模型: %d 顶点 %d 三角 %d 贴图' % (NV, len(IDX) // 3, len(img_bytes)))

# ---------- 骨架（Y-up，+Z 朝脸；新增 jaw） ----------
BONES = {
    'root':   (None,     (0.0, 0.16, -0.02)),
    'spine':  ('root',   (0.0, 0.20, 0.04)),
    'chest':  ('spine',  (0.0, 0.24, 0.10)),
    'neck1':  ('chest',  (0.0, 0.30, 0.14)),
    'neck2':  ('neck1',  (0.0, 0.36, 0.18)),
    'head':   ('neck2',  (0.01, 0.40, 0.225)),
    'jaw':    ('head',   (0.012, 0.376, 0.170)),
    'wingL0': ('chest',  (-0.07, 0.33, 0.05)),
    'wingL1': ('wingL0', (-0.26, 0.38, 0.06)),
    'wingL2': ('wingL1', (-0.44, 0.37, 0.06)),
    'wingR0': ('chest',  (0.07, 0.33, 0.05)),
    'wingR1': ('wingR0', (0.26, 0.38, 0.06)),
    'wingR2': ('wingR1', (0.44, 0.37, 0.06)),
    'legFL0': ('chest',  (-0.065, 0.17, 0.12)),
    'legFL1': ('legFL0', (-0.068, 0.085, 0.125)),
    'legFR0': ('chest',  (0.072, 0.17, 0.12)),
    'legFR1': ('legFR0', (0.075, 0.085, 0.125)),
    'legHL0': ('root',   (-0.058, 0.17, -0.12)),
    'legHL1': ('legHL0', (-0.062, 0.085, -0.125)),
    'legHR0': ('root',   (0.062, 0.17, -0.12)),
    'legHR1': ('legHR0', (0.066, 0.085, -0.125)),
    'tail0':  ('root',   (0.0, 0.13, -0.16)),
    'tail1':  ('tail0',  (-0.01, 0.07, -0.28)),
    'tail2':  ('tail1',  (-0.05, 0.045, -0.42)),
    'tail3':  ('tail2',  (-0.10, 0.04, -0.55)),
}
ORDER = list(BONES.keys())
BIDX = {n: i for i, n in enumerate(ORDER)}
WORLD = {n: BONES[n][1] for n in ORDER}
PARENT = {n: BONES[n][0] for n in ORDER}
CHILDREN = {n: [] for n in ORDER}
for n in ORDER:
    if PARENT[n]:
        CHILDREN[PARENT[n]].append(n)


def wing_tip(sign):
    """从网格量出翼尖位置：翼尖骨原来退化成一点，必须延长到真实翼尖。"""
    m = (sign * P[:, 0] > 0.30) & (P[:, 1] > 0.26)
    if m.sum() < 5:
        return None
    xs = sign * P[m, 0]
    sel = np.zeros(NV, bool)
    sel[np.where(m)[0][xs > xs.max() - 0.04]] = True
    return (float(P[sel, 0].mean()), float(P[sel, 1].mean()), float(P[sel, 2].mean()))


SEG = {}
for n in ORDER:
    p = WORLD[n]
    if PARENT[n] is None:
        a = p
    else:
        a = WORLD[n]
    kids = CHILDREN[n]
    b = WORLD[kids[0]] if kids else a
    SEG[n] = (np.array(a), np.array(b))
# 末端线段手工延长：脚尖 / 尾尖 / 吻端 / 翼尖
for nm, tip in (('legFL1', (-0.068, 0.0, 0.135)), ('legFR1', (0.075, 0.0, 0.135)),
                ('legHL1', (-0.062, 0.0, -0.11)), ('legHR1', (0.066, 0.0, -0.11)),
                ('tail3', (-0.115, 0.045, -0.64)), ('head', (0.01, 0.355, 0.30)),
                ('jaw', (0.012, 0.345, 0.285))):
    SEG[nm] = (SEG[nm][0], np.array(tip))
for nm, sgn in (('wingL2', -1), ('wingR2', 1)):
    tp = wing_tip(sgn)
    if tp:
        SEG[nm] = (SEG[nm][0], np.array(tp))
        print('  翼尖骨 %s 延长到 (%.3f, %.3f, %.3f)' % ((nm,) + tp))

# ---------- 权重：胶囊距离 + 各向异性 + 分区闸门 ----------
RAD = {
    'root': 0.115, 'spine': 0.105, 'chest': 0.115, 'neck1': 0.075, 'neck2': 0.065,
    'head': 0.100, 'jaw': 0.075,
    'wingL0': 0.085, 'wingL1': 0.075, 'wingL2': 0.075,
    'wingR0': 0.085, 'wingR1': 0.075, 'wingR2': 0.075,
    'legFL0': 0.055, 'legFL1': 0.050, 'legFR0': 0.055, 'legFR1': 0.050,
    'legHL0': 0.055, 'legHL1': 0.050, 'legHR0': 0.055, 'legHR1': 0.050,
    'tail0': 0.065, 'tail1': 0.060, 'tail2': 0.050, 'tail3': 0.055,
}
# 翼膜是一张沿 x 展开的薄面，y/z 方向要放宽，否则同一片膜会被相邻两节翼骨平分而撕裂
ANISO = {n: (np.array([1.0, 3.0, 3.0]) if n.startswith('wing') else np.array([1.0, 1.0, 1.0]))
         for n in ORDER}
X, Y, Z = P[:, 0], P[:, 1], P[:, 2]


def ramp(v, lo, hi):
    t = np.clip((v - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3 - 2 * t)


MOUTHLINE = 0.376 - 0.20 * (Z - 0.170)          # 咬合线：后高前低的楔形
JAWG = ramp(Z, 0.115, 0.190) * ramp(MOUTHLINE - Y, 0.0, 0.015) * ramp(Y - (MOUTHLINE - 0.090), 0.0, 0.014)
print('  下颌权重区顶点 %d 个（%.1f%%）' % (int((JAWG > 0.5).sum()), 100.0 * (JAWG > 0.5).mean()))

GATES = {}
for n in ORDER:
    gg = np.ones(NV)
    if n.startswith('wing'):
        gg *= ramp(np.abs(X), 0.07, 0.15) * ramp(P[:, 2], -0.22, -0.10)  # 翼膜只在翼的横向/前后范围内，别抓大腿也别抓尾鳍
    elif n.startswith('leg'):
        gg *= ramp(np.abs(X), 0.018, 0.050)
        gg *= ramp(-X, 0.005, 0.035) if n[4] == 'L' else ramp(X, 0.005, 0.035)
        gg *= ramp(Z, -0.02, 0.03) if n[3] == 'F' else ramp(-Z, -0.02, 0.03)
    elif n.startswith('tail'):
        gg *= ramp(-Z, 0.10, 0.17)
    elif n in ('root', 'spine', 'chest'):
        gg *= ramp(0.24 - np.abs(X), 0.0, 0.09)     # 躯干骨不许伸进翼膜/腿
    if n != 'jaw':
        gg *= (1.0 - 0.85 * JAWG)                   # 下颌区主要归 jaw，别的骨只留一点做过渡
    GATES[n] = gg


def seg_dist_aniso(a, b, s):
    A, B, Q = a / s, b / s, P / s
    dd = B - A
    L2 = float(dd @ dd)
    if L2 < 1e-12:
        return np.linalg.norm(Q - A, axis=1)
    u = np.clip(((Q - A) @ dd) / L2, 0.0, 1.0)
    return np.linalg.norm(Q - (A + u[:, None] * dd), axis=1)


RAW = np.stack([seg_dist_aniso(SEG[n][0], SEG[n][1], ANISO[n]) for n in ORDER], 1)
# 距离先按各骨半径归一，再减去本顶点的最小值（相对化）。
# 绝对式 exp(-(d/r)^2/2) 对“离所有骨都远”的顶点（尾鳍尖、角尖、翼膜外缘）全体趋零，
# 剩下的只是浮点噪声 -> 权重乱分 -> 一播动画就撕（实测 16~22 倍拉伸）。
DD = 0.5 * (RAW / np.array([RAD[n] for n in ORDER])) ** 2
DD -= DD.min(1, keepdims=True)
WGT = np.empty_like(RAW)
for k, n in enumerate(ORDER):
    WGT[:, k] = np.exp(-DD[:, k]) * GATES[n]
rs = WGT.sum(1)
if (rs < 1e-6).any():
    bad = np.where(rs < 1e-6)[0]
    WGT[bad, np.argmin(RAW[bad], 1)] = 1.0
    print('  兜底：%d 个顶点没有任何骨覆盖，直接归最近骨' % len(bad))
WGT /= WGT.sum(1, keepdims=True)

ap = argparse.ArgumentParser()
ap.add_argument('--smooth', type=int, default=2, help='边上权重平滑迭代次数')
ap.add_argument('--dst', default=DST)
A = ap.parse_args()
if A.smooth:
    tri_e = IDX.reshape(-1, 3)
    E = np.unique(np.sort(np.concatenate([tri_e[:, [0, 1]], tri_e[:, [1, 2]], tri_e[:, [2, 0]]]), axis=1), axis=0)
    ia, ib = E[:, 0], E[:, 1]
    for _ in range(A.smooth):
        acc = WGT.copy()
        cnt = np.ones(NV)
        np.add.at(acc, ia, WGT[ib])
        np.add.at(acc, ib, WGT[ia])
        np.add.at(cnt, ia, 1.0)
        np.add.at(cnt, ib, 1.0)
        WGT = 0.65 * WGT + 0.35 * (acc / cnt[:, None])
        WGT /= WGT.sum(1, keepdims=True)
    print('  边上平滑 %d 轮（%d 条边）' % (A.smooth, len(E)))

TOP = np.argsort(-WGT, 1)[:, :4]
TOPW = np.take_along_axis(WGT, TOP, 1)
TOPW /= np.clip(TOPW.sum(1, keepdims=True), 1e-9, None)
dom = TOP[:, 0]
own_r = RAW[np.arange(NV), dom] / np.array([RAD[n] for n in ORDER])[dom]
fm = own_r > 3.0
if fm.any():
    cnt = np.bincount(dom[fm], minlength=len(ORDER))
    g5 = list(np.argsort(-cnt)[:5])
    print("  远顶点(离自家骨>3倍半径): %d 个 (%.1f%%)  %s" % (int(fm.sum()), 100.0 * fm.mean(),
          "  ".join("%s %d" % (ORDER[k], cnt[k]) for k in g5 if cnt[k])))
    for k in g5:
        m = fm & (dom == k)
        if m.sum() < 5:
            continue
        print("     %-7s %4d  x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f]" % (
            ORDER[k], int(m.sum()), P[m, 0].min(), P[m, 0].max(), P[m, 1].min(), P[m, 1].max(),
            P[m, 2].min(), P[m, 2].max()))
print('  权重质量（前 8）: ' + '  '.join('%s %.3f' % (ORDER[k], WGT[:, k].mean())
                                         for k in np.argsort(-WGT.mean(0))[:8]))
print('  主导骨分布（前 10）: ' + '  '.join('%s %d' % (ORDER[k], int((dom == k).sum()))
                                           for k in np.argsort(-np.bincount(dom, minlength=len(ORDER)))[:10]))

# ---------- 动画：预备 -> 出招 -> 收招 ----------
# 所有骨骼静止时局部旋转为单位阵，所以局部轴 == 模型轴：
#   +rotX：头部/躯干低头前俯；腿骨朝下，+rotX 把爪子向后甩（前抬用负值）
#   +rotY：朝模型右侧（+x）转；+rotZ：左侧下沉（左翼尖向上用负值）
CLIPS = {
    'idle': {'dur': 3.6, 'rot': {
        'wingL0': [(0, (0, 0, -6)), (1.8, (0, 0, 7)), (3.6, (0, 0, -6))],
        'wingR0': [(0, (0, 0, 6)), (1.8, (0, 0, -7)), (3.6, (0, 0, 6))],
        'wingL1': [(0, (0, 0, -9)), (1.8, (0, 0, 10)), (3.6, (0, 0, -9))],
        'wingR1': [(0, (0, 0, 9)), (1.8, (0, 0, -10)), (3.6, (0, 0, 9))],
        'neck1': [(0, (0, 3, 0)), (1.8, (0, -3, 0)), (3.6, (0, 3, 0))],
        'head': [(0, (2, -4, 0)), (1.8, (2, 4, 0)), (3.6, (2, -4, 0))],
        'jaw': [(0, (0, 0, 0)), (1.6, (4, 0, 0)), (2.6, (1, 0, 0)), (3.6, (0, 0, 0))],
        'chest': [(0, (1.5, 0, 0)), (0.9, (3.5, 0, 0)), (1.8, (1.5, 0, 0)), (2.7, (3.5, 0, 0)), (3.6, (1.5, 0, 0))],
        'tail1': [(0, (0, 10, 0)), (1.8, (0, -10, 0)), (3.6, (0, 10, 0))],
        'tail2': [(0, (0, 14, 0)), (1.8, (0, -14, 0)), (3.6, (0, 14, 0))],
        'tail3': [(0, (0, 18, 0)), (1.8, (0, -18, 0)), (3.6, (0, 18, 0))],
    }},
    'flap': {'dur': 0.9, 'rot': {
        'wingL0': [(0, (0, 0, -34)), (0.45, (0, 0, 30)), (0.9, (0, 0, -34))],
        'wingR0': [(0, (0, 0, 34)), (0.45, (0, 0, -30)), (0.9, (0, 0, 34))],
        'wingL1': [(0, (0, 0, -18)), (0.45, (0, 0, 44)), (0.9, (0, 0, -18))],
        'wingR1': [(0, (0, 0, 18)), (0.45, (0, 0, -44)), (0.9, (0, 0, 18))],
        'wingL2': [(0, (0, 0, -8)), (0.45, (0, 0, 26)), (0.9, (0, 0, -8))],
        'wingR2': [(0, (0, 0, 8)), (0.45, (0, 0, -26)), (0.9, (0, 0, 8))],
        'legFL0': [(0, (26, 0, 0)), (0.9, (26, 0, 0))],
        'legFR0': [(0, (26, 0, 0)), (0.9, (26, 0, 0))],
        'legHL0': [(0, (-20, 0, 0)), (0.9, (-20, 0, 0))],
        'legHR0': [(0, (-20, 0, 0)), (0.9, (-20, 0, 0))],
        'legFL1': [(0, (30, 0, 0)), (0.9, (30, 0, 0))],
        'legFR1': [(0, (30, 0, 0)), (0.9, (30, 0, 0))],
        'legHL1': [(0, (30, 0, 0)), (0.9, (30, 0, 0))],
        'legHR1': [(0, (30, 0, 0)), (0.9, (30, 0, 0))],
        'tail1': [(0, (0, 8, 0)), (0.45, (0, -8, 0)), (0.9, (0, 8, 0))],
        'tail2': [(0, (0, 12, 0)), (0.45, (0, -12, 0)), (0.9, (0, 12, 0))],
        'neck1': [(0, (-4, 0, 0)), (0.45, (2, 0, 0)), (0.9, (-4, 0, 0))],
    }},
    # 咬：0.40 前是仰头缩颈张嘴的预备，0.52 是咬合命中帧，之后收招
    'bite': {'dur': 1.0, 'rot': {
        'neck1': [(0, (0, 0, 0)), (0.40, (-14, 0, 0)), (0.52, (15, 0, 0)), (0.70, (3, 0, 0)), (1.0, (0, 0, 0))],
        'neck2': [(0, (0, 0, 0)), (0.40, (-13, 0, 0)), (0.52, (22, 0, 0)), (0.70, (4, 0, 0)), (1.0, (0, 0, 0))],
        'head':  [(0, (0, 0, 0)), (0.34, (-16, 0, 0)), (0.40, (-22, 0, 0)), (0.52, (33, 0, 0)), (0.72, (6, 0, 0)), (1.0, (0, 0, 0))],
        'jaw':   [(0, (0, 0, 0)), (0.22, (10, 0, 0)), (0.40, (23, 0, 0)), (0.50, (14, 0, 0)), (0.53, (1, 0, 0)), (1.0, (0, 0, 0))],
        'chest': [(0, (0, 0, 0)), (0.40, (-6, 0, 0)), (0.52, (8, 0, 0)), (1.0, (0, 0, 0))],
        'wingL0': [(0, (0, 0, -6)), (0.40, (0, -6, -20)), (0.52, (0, 4, -10)), (1.0, (0, 0, -6))],
        'wingR0': [(0, (0, 0, 6)), (0.40, (0, 6, 20)), (0.52, (0, -4, 10)), (1.0, (0, 0, 6))],
        'tail1': [(0, (0, 8, 0)), (0.40, (0, -8, 0)), (0.60, (0, 10, 0)), (1.0, (0, 8, 0))],
    }, 'trans': {
        'root': [(0, (0, 0, 0)), (0.40, (0, 0, -0.018)), (0.52, (0, 0, 0.075)), (0.74, (0, 0, 0.010)), (1.0, (0, 0, 0))],
    }},
    # 爪击：右前爪抬起外张 -> 斜扫到下前方（配躯干回转），0.56 命中
    'claw': {'dur': 1.05, 'rot': {
        'legFR0': [(0, (0, 0, 0)), (0.30, (-40, 0, 20)), (0.42, (-72, 0, 30)), (0.56, (4, 0, -34)), (0.78, (-10, 0, -12)), (1.05, (0, 0, 0))],
        'legFR1': [(0, (0, 0, 0)), (0.30, (26, 0, 0)), (0.42, (44, 0, 0)), (0.56, (-16, 0, 0)), (0.78, (10, 0, 0)), (1.05, (0, 0, 0))],
        'legFL0': [(0, (0, 0, 0)), (0.42, (16, 0, 0)), (0.56, (-12, 0, 0)), (1.05, (0, 0, 0))],
        'legFL1': [(0, (0, 0, 0)), (0.42, (-10, 0, 0)), (0.56, (14, 0, 0)), (1.05, (0, 0, 0))],
        'legHL0': [(0, (0, 0, 0)), (0.42, (-10, 0, 0)), (0.56, (8, 0, 0)), (1.05, (0, 0, 0))],
        'legHR0': [(0, (0, 0, 0)), (0.42, (-10, 0, 0)), (0.56, (8, 0, 0)), (1.05, (0, 0, 0))],
        'spine':  [(0, (0, 0, 0)), (0.42, (0, -15, 0)), (0.56, (0, 17, 0)), (0.78, (0, 5, 0)), (1.05, (0, 0, 0))],
        'root':   [(0, (0, 0, 0)), (0.42, (0, -11, 0)), (0.56, (0, 13, 0)), (0.78, (0, 4, 0)), (1.05, (0, 0, 0))],
        'chest':  [(0, (0, 0, 0)), (0.42, (-5, -10, 0)), (0.56, (7, 15, 0)), (1.05, (0, 0, 0))],
        'head':   [(0, (0, 0, 0)), (0.42, (2, -17, 0)), (0.56, (8, 19, 0)), (0.78, (2, 4, 0)), (1.05, (0, 0, 0))],
        'jaw':    [(0, (0, 0, 0)), (0.30, (12, 0, 0)), (0.42, (18, 0, 0)), (0.56, (8, 0, 0)), (1.05, (0, 0, 0))],
        'wingL0': [(0, (0, 0, -6)), (0.42, (0, 0, -26)), (0.56, (0, 0, -12)), (1.05, (0, 0, -6))],
        'wingR0': [(0, (0, 0, 6)), (0.42, (0, 0, 22)), (0.56, (0, 0, 10)), (1.05, (0, 0, 6))],
        'wingL1': [(0, (0, 0, -9)), (0.42, (0, 0, -16)), (1.05, (0, 0, -9))],
        'wingR1': [(0, (0, 0, 9)), (0.42, (0, 0, 14)), (1.05, (0, 0, 9))],
        'tail1':  [(0, (0, 6, 0)), (0.42, (0, -14, 0)), (0.56, (0, 12, 0)), (1.05, (0, 6, 0))],
        'tail2':  [(0, (0, 9, 0)), (0.42, (0, -18, 0)), (0.56, (0, 16, 0)), (1.05, (0, 9, 0))],
    }, 'trans': {
        'root': [(0, (0, 0, 0)), (0.42, (0.01, 0, -0.022)), (0.56, (-0.01, 0, 0.05)), (0.80, (0, 0, 0.008)), (1.05, (0, 0, 0))],
    }},
    # 尾扫：尾巴先向后外盘起，再横扫过侧面，0.68 命中
    'sweep': {'dur': 1.15, 'rot': {
        'tail0': [(0, (0, 0, 0)), (0.42, (0, -20, 0)), (0.62, (0, 30, 0)), (0.88, (0, 6, 0)), (1.15, (0, 0, 0))],
        'tail1': [(0, (0, 0, 0)), (0.42, (0, -26, 0)), (0.66, (0, 42, 0)), (0.90, (0, 8, 0)), (1.15, (0, 0, 0))],
        'tail2': [(0, (0, 0, 0)), (0.42, (0, -30, 0)), (0.70, (0, 50, 0)), (0.92, (0, 10, 0)), (1.15, (0, 0, 0))],
        'tail3': [(0, (0, 0, 0)), (0.42, (0, -34, 0)), (0.74, (0, 58, 0)), (0.94, (0, 12, 0)), (1.15, (0, 0, 0))],
        'root':  [(0, (0, 0, 0)), (0.42, (0, -9, 0)), (0.68, (0, 11, 0)), (1.15, (0, 0, 0))],
        'spine': [(0, (0, 0, 0)), (0.42, (0, -7, 0)), (0.68, (0, 9, 0)), (1.15, (0, 0, 0))],
        'head':  [(0, (0, 0, 0)), (0.42, (0, -16, 0)), (0.68, (0, 18, 0)), (1.15, (0, 0, 0))],
        'jaw':   [(0, (0, 0, 0)), (0.42, (14, 0, 0)), (0.68, (9, 0, 0)), (1.15, (0, 0, 0))],
        'wingL0': [(0, (0, 0, -6)), (0.5, (0, 0, -22)), (1.15, (0, 0, -6))],
        'wingR0': [(0, (0, 0, 6)), (0.5, (0, 0, 22)), (1.15, (0, 0, 6))],
    }, 'trans': {
        'root': [(0, (0, 0, 0)), (0.42, (0.008, 0, -0.01)), (0.68, (-0.008, 0, 0.012)), (1.15, (0, 0, 0))],
    }},
    # 吐息：0.62 前是吸气蓄力（仰头张嘴、翼半张），0.62-2.05 持续喷焰
    'breath': {'dur': 2.6, 'rot': {
        'neck1': [(0, (0, 0, 0)), (0.62, (-15, 0, 0)), (0.80, (11, 0, 0)), (2.05, (9, 0, 0)), (2.6, (0, 0, 0))],
        'neck2': [(0, (0, 0, 0)), (0.62, (-13, 0, 0)), (0.80, (13, 0, 0)), (2.05, (11, 0, 0)), (2.6, (0, 0, 0))],
        'head':  [(0, (0, 0, 0)), (0.30, (-17, 0, 0)), (0.62, (-23, 0, 0)), (0.80, (16, 0, 0)), (1.40, (13, 0, 0)), (2.05, (16, 0, 0)), (2.6, (0, 0, 0))],
        'jaw':   [(0, (0, 0, 0)), (0.32, (12, 0, 0)), (0.62, (26, 0, 0)), (0.85, (20, 0, 0)), (1.50, (23, 0, 0)), (2.05, (17, 0, 0)), (2.6, (0, 0, 0))],
        'chest': [(0, (0, 0, 0)), (0.55, (-8, 0, 0)), (0.80, (5, 0, 0)), (2.05, (4, 0, 0)), (2.6, (0, 0, 0))],
        'wingL0': [(0, (0, 0, -6)), (0.62, (0, -16, -20)), (0.90, (0, -10, -10)), (2.05, (0, -15, -16)), (2.6, (0, 0, -6))],
        'wingR0': [(0, (0, 0, 6)), (0.62, (0, 16, 20)), (0.90, (0, 10, 10)), (2.05, (0, 15, 16)), (2.6, (0, 0, 6))],
        'wingL1': [(0, (0, 0, -9)), (0.62, (0, -8, -14)), (2.05, (0, -8, -12)), (2.6, (0, 0, -9))],
        'wingR1': [(0, (0, 0, 9)), (0.62, (0, 8, 14)), (2.05, (0, 8, 12)), (2.6, (0, 0, 9))],
        'tail1':  [(0, (0, 6, 0)), (1.30, (0, -6, 0)), (2.6, (0, 6, 0))],
        'tail2':  [(0, (0, 9, 0)), (1.30, (0, -9, 0)), (2.6, (0, 9, 0))],
    }, 'trans': {
        'root': [(0, (0, 0, 0)), (0.62, (0, 0.015, -0.015)), (0.80, (0, 0, 0.03)), (2.05, (0, 0, 0.03)), (2.6, (0, 0, 0))],
    }},
    # 蓄力吐火球：下蹲压低 -> 0.60 前冲吐球
    'charge': {'dur': 1.45, 'rot': {
        'neck1': [(0, (0, 0, 0)), (0.45, (11, 0, 0)), (0.60, (-7, 0, 0)), (1.15, (0, 0, 0))],
        'neck2': [(0, (0, 0, 0)), (0.45, (13, 0, 0)), (0.60, (-5, 0, 0)), (1.15, (0, 0, 0))],
        'head':  [(0, (0, 0, 0)), (0.30, (9, 0, 0)), (0.45, (15, 0, 0)), (0.60, (1, 0, 0)), (0.78, (-6, 0, 0)), (1.15, (0, 0, 0))],
        'jaw':   [(0, (0, 0, 0)), (0.30, (10, 0, 0)), (0.45, (18, 0, 0)), (0.60, (27, 0, 0)), (0.78, (20, 0, 0)), (1.15, (0, 0, 0))],
        'chest': [(0, (0, 0, 0)), (0.45, (-7, 0, 0)), (0.60, (-10, 0, 0)), (0.85, (4, 0, 0)), (1.15, (0, 0, 0))],
        'wingL0': [(0, (0, 0, -6)), (0.50, (0, 0, -30)), (0.62, (0, 0, -14)), (1.15, (0, 0, -6))],
        'wingR0': [(0, (0, 0, 6)), (0.50, (0, 0, 30)), (0.62, (0, 0, 14)), (1.15, (0, 0, 6))],
        'legFL0': [(0, (0, 0, 0)), (0.45, (18, 0, 0)), (0.62, (-14, 0, 0)), (1.15, (0, 0, 0))],
        'legFR0': [(0, (0, 0, 0)), (0.45, (18, 0, 0)), (0.62, (-14, 0, 0)), (1.15, (0, 0, 0))],
        'legHL0': [(0, (0, 0, 0)), (0.45, (-16, 0, 0)), (0.62, (10, 0, 0)), (1.15, (0, 0, 0))],
        'legHR0': [(0, (0, 0, 0)), (0.45, (-16, 0, 0)), (0.62, (10, 0, 0)), (1.15, (0, 0, 0))],
        'tail1':  [(0, (0, 8, 0)), (0.45, (0, -10, 0)), (0.62, (0, 14, 0)), (1.15, (0, 8, 0))],
    }, 'trans': {
        'root': [(0, (0, 0, 0)), (0.45, (0, -0.030, -0.012)), (0.60, (0, 0.018, 0.045)), (0.85, (0, 0, 0.012)), (1.15, (0, 0, 0)), (1.45, (0, 0, 0))],
    }},
    'roar': {'dur': 1.5, 'rot': {
        'neck1': [(0, (0, 0, 0)), (0.4, (-10, 0, 0)), (1.1, (-10, 0, 0)), (1.5, (0, 0, 0))],
        'neck2': [(0, (0, 0, 0)), (0.4, (-8, 0, 0)), (1.1, (-8, 0, 0)), (1.5, (0, 0, 0))],
        'head':  [(0, (0, 0, 0)), (0.4, (-24, 0, 0)), (1.1, (-24, 0, 0)), (1.5, (0, 0, 0))],
        'jaw':   [(0, (0, 0, 0)), (0.22, (16, 0, 0)), (0.40, (29, 0, 0)), (1.05, (31, 0, 0)), (1.28, (12, 0, 0)), (1.5, (0, 0, 0))],
        'wingL0': [(0, (0, 0, -6)), (0.4, (0, 0, -38)), (1.1, (0, 0, -38)), (1.5, (0, 0, -6))],
        'wingR0': [(0, (0, 0, 6)), (0.4, (0, 0, 38)), (1.1, (0, 0, 38)), (1.5, (0, 0, 6))],
        'wingL1': [(0, (0, 0, -9)), (0.4, (0, 0, -30)), (1.1, (0, 0, -30)), (1.5, (0, 0, -9))],
        'wingR1': [(0, (0, 0, 9)), (0.4, (0, 0, 30)), (1.1, (0, 0, 30)), (1.5, (0, 0, 9))],
        'chest': [(0, (0, 0, 0)), (0.4, (-5, 0, 0)), (1.1, (-5, 0, 0)), (1.5, (0, 0, 0))],
        'tail1': [(0, (0, 10, 0)), (0.75, (0, -10, 0)), (1.5, (0, 10, 0))],
        'tail2': [(0, (0, 14, 0)), (0.75, (0, -14, 0)), (1.5, (0, 14, 0))],
    }, 'trans': {
        'root': [(0, (0, 0, 0)), (0.4, (0, 0.02, 0)), (1.1, (0, 0.02, 0)), (1.5, (0, 0, 0))],
    }},
    'hurt': {'dur': 0.35, 'rot': {
        'spine': [(0, (0, 0, 0)), (0.08, (-8, 0, 0)), (0.35, (0, 0, 0))],
        'head':  [(0, (0, 0, 0)), (0.08, (0, 14, 0)), (0.18, (0, -10, 0)), (0.35, (0, 0, 0))],
        'neck1': [(0, (0, 0, 0)), (0.08, (-6, 0, 0)), (0.35, (0, 0, 0))],
        'jaw':   [(0, (0, 0, 0)), (0.09, (17, 0, 0)), (0.35, (0, 0, 0))],
    }},
    'death': {'dur': 1.4, 'rot': {
        'root':  [(0, (0, 0, 0)), (0.7, (4, 0, 26)), (1.1, (6, 0, 38)), (1.4, (6, 0, 40))],
        'neck1': [(0, (0, 0, 0)), (0.9, (16, 0, 6)), (1.4, (20, 0, 8))],
        'neck2': [(0, (0, 0, 0)), (0.9, (18, 0, 6)), (1.4, (22, 0, 8))],
        'head':  [(0, (0, 0, 0)), (0.9, (14, 10, 10)), (1.4, (16, 12, 12))],
        'jaw':   [(0, (0, 0, 0)), (0.5, (14, 0, 0)), (0.9, (22, 0, 0)), (1.4, (18, 0, 0))],
        'wingL0': [(0, (0, 0, -6)), (1.0, (0, 0, 26)), (1.4, (0, 0, 30))],
        'wingR0': [(0, (0, 0, 6)), (1.0, (0, 0, 20)), (1.4, (0, 0, 24))],
        'wingL1': [(0, (0, 0, -9)), (1.0, (0, 0, 22)), (1.4, (0, 0, 26))],
        'wingR1': [(0, (0, 0, 9)), (1.0, (0, 0, 18)), (1.4, (0, 0, 22))],
        'tail1': [(0, (0, 10, 0)), (1.4, (0, 4, 0))],
        'tail2': [(0, (0, 14, 0)), (1.4, (0, 6, 0))],
    }, 'trans': {
        'root': [(0, (0, 0, 0)), (0.7, (0, -0.05, 0)), (1.1, (0, -0.085, 0)), (1.4, (0, -0.09, 0))],
    }},
}

# ---------- 打包 GLB ----------
D = math.pi / 180


def q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def q_euler(rx, ry, rz):
    qx = (math.sin(rx / 2), 0, 0, math.cos(rx / 2))
    qy = (0, math.sin(ry / 2), 0, math.cos(ry / 2))
    qz = (0, 0, math.sin(rz / 2), math.cos(rz / 2))
    return q_mul(q_mul(qx, qy), qz)


bin_parts, bvs, offset = [], [], 0


def add_bv(data, target=None):
    global offset
    pad = (4 - offset % 4) % 4
    if pad:
        bin_parts.append(b'\0' * pad)
        offset += pad
    bv = {'buffer': 0, 'byteOffset': offset, 'byteLength': len(data)}
    if target:
        bv['target'] = target
    bvs.append(bv)
    bin_parts.append(data)
    offset += len(data)
    return len(bvs) - 1


b_img = [add_bv(im) for im in img_bytes]
b_pos = add_bv(P.astype('<f4').tobytes(), 34962)
b_nor = add_bv(N.astype('<f4').tobytes(), 34962)
b_uv = add_bv(UV.astype('<f4').tobytes(), 34962)
b_jnt = add_bv(TOP.astype('<u1').tobytes(), 34962)
b_wgt = add_bv(TOPW.astype('<f4').tobytes(), 34962)
b_idx = add_bv(IDX.astype('<u4').tobytes(), 34963)
ibm = array.array('f')
for n in ORDER:
    x, y, z = WORLD[n]
    if n == 'jaw':
        x, y, z = WORLD['jaw']            # IBM 用关节自身静止位置
    ibm.extend([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -x, -y, -z, 1])
b_ibm = add_bv(ibm.tobytes())

accessors = [
    {'bufferView': b_pos, 'componentType': 5126, 'count': NV, 'type': 'VEC3',
     'min': [float(P[:, i].min()) for i in range(3)], 'max': [float(P[:, i].max()) for i in range(3)]},
    {'bufferView': b_nor, 'componentType': 5126, 'count': NV, 'type': 'VEC3'},
    {'bufferView': b_uv, 'componentType': 5126, 'count': NV, 'type': 'VEC2'},
    {'bufferView': b_jnt, 'componentType': 5121, 'count': NV, 'type': 'VEC4'},
    {'bufferView': b_wgt, 'componentType': 5126, 'count': NV, 'type': 'VEC4'},
    {'bufferView': b_idx, 'componentType': 5125, 'count': len(IDX), 'type': 'SCALAR'},
    {'bufferView': b_ibm, 'componentType': 5126, 'count': len(ORDER), 'type': 'MAT4'},
]
ACC_IBM = 6

animations = []
for clip_name, clip in CLIPS.items():
    samplers, channels = [], []

    def add_channel(bone, path, keys):
        times = array.array('f', [k[0] for k in keys])
        vals = array.array('f')
        if path == 'rotation':
            for _, e in keys:
                vals.extend(q_euler(e[0] * D, e[1] * D, e[2] * D))
            vtype = 'VEC4'
        else:
            for _, v in keys:
                vals.extend(v)
            vtype = 'VEC3'
        bt = add_bv(times.tobytes())
        bv_ = add_bv(vals.tobytes())
        accessors.append({'bufferView': bt, 'componentType': 5126, 'count': len(keys),
                          'type': 'SCALAR', 'min': [min(times)], 'max': [max(times)]})
        accessors.append({'bufferView': bv_, 'componentType': 5126, 'count': len(keys), 'type': vtype})
        samplers.append({'input': len(accessors) - 2, 'output': len(accessors) - 1, 'interpolation': 'LINEAR'})
        channels.append({'sampler': len(samplers) - 1, 'target': {'node': 1 + BIDX[bone], 'path': path}})
    for bone, keys in clip.get('rot', {}).items():
        assert bone in BIDX, bone
        add_channel(bone, 'rotation', keys)
    for bone, keys in clip.get('trans', {}).items():
        par = PARENT[bone]
        base = list(WORLD[bone]) if par is None else [WORLD[bone][i] - WORLD[par][i] for i in range(3)]
        add_channel(bone, 'translation', [(t, (base[0] + v[0], base[1] + v[1], base[2] + v[2])) for t, v in keys])
    animations.append({'name': clip_name, 'samplers': samplers, 'channels': channels})

nodes = [{'mesh': 0, 'skin': 0, 'name': 'dragon-rigged'}]
for n in ORDER:
    par = PARENT[n]
    loc = WORLD[n] if par is None else tuple(WORLD[n][i] - WORLD[par][i] for i in range(3))
    node = {'name': n, 'translation': list(loc)}
    if CHILDREN[n]:
        node['children'] = [1 + BIDX[c] for c in CHILDREN[n]]
    nodes.append(node)

new_g = {
    'asset': {'version': '2.0', 'generator': 'DragonKnight dragon rerig (weights + jaw)'},
    'scene': 0, 'scenes': [{'nodes': [0, 1]}],
    'nodes': nodes,
    'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2,
                                               'JOINTS_0': 3, 'WEIGHTS_0': 4},
                                'indices': 5, 'material': 0}]}],
    'materials': g['materials'],
    'textures': g['textures'],
    'samplers': g.get('samplers', []),
    'images': [{'bufferView': b_img[i], 'mimeType': g['images'][i].get('mimeType', 'image/webp')}
               for i in range(len(img_bytes))],
    'bufferViews': bvs,
    'accessors': accessors,
    'skins': [{'joints': [1 + i for i in range(len(ORDER))], 'inverseBindMatrices': ACC_IBM, 'skeleton': 1}],
    'animations': animations,
    'buffers': [{'byteLength': offset}],
}
if g.get('extensionsUsed'):
    new_g['extensionsUsed'] = g['extensionsUsed']
jb = json.dumps(new_g).encode()
jb += b' ' * ((4 - len(jb) % 4) % 4)
binb = b''.join(bin_parts)
binb += b'\0' * ((4 - len(binb) % 4) % 4)
total = 12 + 8 + len(jb) + 8 + len(binb)
out = (struct.pack('<III', 0x46546C67, 2, total) + struct.pack('<II', len(jb), 0x4E4F534A) + jb
       + struct.pack('<II', len(binb), 0x004E4942) + binb)
open(A.dst, 'wb').write(out)
if A.dst == DST: open(B64, 'w').write(base64.b64encode(out).decode())
print('写出 %s  %.2f MB  骨骼 %d  片段 %s' % (A.dst, len(out) / 1e6, len(ORDER), list(CLIPS)))
