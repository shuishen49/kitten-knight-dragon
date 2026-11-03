#!/usr/bin/env python3
"""给 dragon1.glb 绑骨骼 + 烘焙动画，输出 dragon-anim.glb。
源模型节点带 +90°X 旋转（Z-up），先把旋转烘进顶点，得到 Y-up、+Z 朝脸的干净空间再绑骨。
权重：顶点到骨骼线段的距离衰减 + 区域规则（翼膜/头/尾/腿优先池）。
骨骼/动画设计对应游戏龙状态机：idle/flap/breath/bite/sweep/roar/hurt/death。"""
import struct, json, array, math

SRC = 'dragon1.glb'
DST = 'dragon-anim.glb'

# ---------- 读源 GLB ----------
d = open(SRC, 'rb').read()
jlen = struct.unpack('<I', d[12:16])[0]
g = json.loads(d[20:20 + jlen])
bin_off = 20 + jlen + 8
prim = g['meshes'][0]['primitives'][0]
def acc_bytes(ai):
    acc = g['accessors'][ai]; bv = g['bufferViews'][acc['bufferView']]
    return bin_off + bv.get('byteOffset', 0) + acc.get('byteOffset', 0), acc
ps, pacc = acc_bytes(prim['attributes']['POSITION'])
NV = pacc['count']
pos_l = array.array('f'); pos_l.frombytes(d[ps:ps + NV * 12])
ns, nacc = acc_bytes(prim['attributes']['NORMAL'])
nor_l = array.array('f'); nor_l.frombytes(d[ns:ns + NV * 12])
ts, tacc = acc_bytes(prim['attributes']['TEXCOORD_0'])
uv = array.array('f'); uv.frombytes(d[ts:ts + NV * 8])
is_, iacc = acc_bytes(prim['indices'])
itype = 'H' if iacc['componentType'] == 5123 else 'I'
idx = array.array(itype); idx.frombytes(d[is_:is_ + iacc['count'] * (2 if itype == 'H' else 4)])
idx = array.array('I', idx.tolist())
# 烘焙节点旋转：local (x,y,z) -> world (x, -z, y)
pos = array.array('f', [0.0]) * (NV * 3)
nor = array.array('f', [0.0]) * (NV * 3)
for i in range(NV):
    x, y, z = pos_l[i * 3], pos_l[i * 3 + 1], pos_l[i * 3 + 2]
    pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2] = x, -z, y
    nx, ny, nz = nor_l[i * 3], nor_l[i * 3 + 1], nor_l[i * 3 + 2]
    nor[i * 3], nor[i * 3 + 1], nor[i * 3 + 2] = nx, -nz, ny
P = [(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]) for i in range(NV)]
# 源贴图字节（按 images 顺序：0 法线、1 底色、2 金属粗糙）
img_bytes = []
for im in g['images']:
    bv = g['bufferViews'][im['bufferView']]
    o = bin_off + bv.get('byteOffset', 0)
    img_bytes.append(d[o:o + bv['byteLength']])

# ---------- 骨架（Y-up 世界位置，+Z 朝脸） ----------
BONES = {
    'root':   (None,   (0.0, 0.16, -0.02)),
    'spine':  ('root', (0.0, 0.20, 0.04)),
    'chest':  ('spine', (0.0, 0.24, 0.10)),
    'neck1':  ('chest', (0.0, 0.30, 0.14)),
    'neck2':  ('neck1', (0.0, 0.36, 0.18)),
    'head':   ('neck2', (0.01, 0.40, 0.225)),
    'wingL0': ('chest', (-0.07, 0.33, 0.05)),
    'wingL1': ('wingL0', (-0.26, 0.38, 0.06)),
    'wingL2': ('wingL1', (-0.44, 0.37, 0.06)),
    'wingR0': ('chest', (0.07, 0.33, 0.05)),
    'wingR1': ('wingR0', (0.26, 0.38, 0.06)),
    'wingR2': ('wingR1', (0.44, 0.37, 0.06)),
    'legFL0': ('chest', (-0.065, 0.17, 0.12)),
    'legFL1': ('legFL0', (-0.068, 0.085, 0.125)),
    'legFR0': ('chest', (0.072, 0.17, 0.12)),
    'legFR1': ('legFR0', (0.075, 0.085, 0.125)),
    'legHL0': ('root', (-0.058, 0.17, -0.12)),
    'legHL1': ('legHL0', (-0.062, 0.085, -0.125)),
    'legHR0': ('root', (0.062, 0.17, -0.12)),
    'legHR1': ('legHR0', (0.066, 0.085, -0.125)),
    'tail0':  ('root', (0.0, 0.13, -0.16)),
    'tail1':  ('tail0', (-0.01, 0.07, -0.28)),
    'tail2':  ('tail1', (-0.05, 0.045, -0.42)),
    'tail3':  ('tail2', (-0.10, 0.04, -0.55)),
}
ORDER = list(BONES.keys())
BIDX = {n: i for i, n in enumerate(ORDER)}
WORLD = {n: BONES[n][1] for n in ORDER}
PARENT = {n: BONES[n][0] for n in ORDER}
CHILDREN = {n: [] for n in ORDER}
for n in ORDER:
    if PARENT[n]: CHILDREN[PARENT[n]].append(n)
def seg_of(name):
    p = WORLD[name]
    if CHILDREN[name]:
        return (p, WORLD[CHILDREN[name][0]])
    return (p, p)
SEG = {n: seg_of(n) for n in ORDER}
# 手工延长末端线段（脚尖/尾尖/吻部）
SEG['legFL1'] = (WORLD['legFL1'], (-0.068, 0.0, 0.135))
SEG['legFR1'] = (WORLD['legFR1'], (0.075, 0.0, 0.135))
SEG['legHL1'] = (WORLD['legHL1'], (-0.062, 0.0, -0.11))
SEG['legHR1'] = (WORLD['legHR1'], (0.066, 0.0, -0.11))
SEG['tail3'] = (WORLD['tail3'], (-0.115, 0.045, -0.64))
SEG['head'] = (WORLD['head'], (0.01, 0.355, 0.30))

# ---------- 权重 ----------
def dist_seg(p, a, b):
    ax, ay, az = a; bx, by, bz = b; px, py, pz = p
    dx, dy, dz = bx - ax, by - ay, bz - az
    L2 = dx * dx + dy * dy + dz * dz
    t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy + (pz - az) * dz) / L2))
    cx, cy, cz = ax + t * dx, ay + t * dy, az + t * dz
    return math.sqrt((px - cx) ** 2 + (py - cy) ** 2 + (pz - cz) ** 2)
def vdist(a, b): return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)

RAD = {'root': 0.30, 'spine': 0.16, 'chest': 0.17, 'neck1': 0.10, 'neck2': 0.09, 'head': 0.30,
       'wingL0': 0.11, 'wingL1': 0.10, 'wingL2': 0.11, 'wingR0': 0.11, 'wingR1': 0.10, 'wingR2': 0.11,
       'legFL0': 0.075, 'legFL1': 0.07, 'legFR0': 0.075, 'legFR1': 0.07,
       'legHL0': 0.075, 'legHL1': 0.07, 'legHR0': 0.075, 'legHR1': 0.07,
       'tail0': 0.08, 'tail1': 0.075, 'tail2': 0.07, 'tail3': 0.075}
HEAD_C = (0.01, 0.40, 0.225)
LEG_HIPS = {'legFL': (-0.065, 0.12), 'legFR': (0.072, 0.12), 'legHL': (-0.058, -0.12), 'legHR': (0.062, -0.12)}
joints = array.array('B'); weights = array.array('f')
for i in range(NV):
    p = P[i]; x, y, z = p
    dx = (x - HEAD_C[0]) / 0.085; dy = (y - HEAD_C[1]) / 0.115; dz = (z - HEAD_C[2]) / 0.08
    if dx * dx + dy * dy + dz * dz < 1.0:
        pool = ['head', 'neck2']
    elif y >= 0.285 and z <= 0.17 and abs(x) >= 0.095:
        s = 'L' if x < 0 else 'R'
        pool = [f'wing{s}0', f'wing{s}1', 'chest'] if abs(x) < 0.20 else [f'wing{s}0', f'wing{s}1', f'wing{s}2']
    elif z <= -0.185 and y <= 0.20:
        pool = ['tail0', 'tail1', 'tail2', 'tail3', 'root']
    elif y <= 0.185:
        best, bd = None, 1e9
        for ln, (lx, lz) in LEG_HIPS.items():
            dd = (x - lx) ** 2 + (z - lz) ** 2
            if dd < bd: bd, best = dd, ln
        pool = [best + '0', best + '1', 'root'] if bd < 0.085 ** 2 else ['root', 'spine', 'chest']
    elif z >= 0.125 and abs(x) <= 0.075 and y >= 0.26:
        pool = ['neck1', 'neck2', 'head', 'chest']
    else:
        pool = ['root', 'spine', 'chest', 'neck1']
    cand = []
    for bn in pool:
        dd = dist_seg(p, *SEG[bn]); r = RAD[bn]
        cand.append((math.exp(-(dd * dd) / (2 * r * r)), bn))
    cand.sort(reverse=True)
    top = cand[:4]; ssum = sum(w for w, _ in top) or 1.0
    js = [BIDX[bn] for _, bn in top] + [0] * (4 - len(top))
    ws = [w / ssum for w, _ in top] + [0.0] * (4 - len(top))
    joints.extend(js); weights.extend(ws)
print('weights done')

# ---------- 四元数 ----------
def q_mul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)
def q_euler(rx, ry, rz):
    qx = (math.sin(rx / 2), 0, 0, math.cos(rx / 2))
    qy = (0, math.sin(ry / 2), 0, math.cos(ry / 2))
    qz = (0, 0, math.sin(rz / 2), math.cos(rz / 2))
    return q_mul(q_mul(qx, qy), qz)

# ---------- 动画 ----------
# 翼扇动：左翼尖向上 = rz 为负；右翼镜像为正。rotX 正值 = 低头（朝 +Z 下俯）。
D = math.pi / 180
CLIPS = {
  'idle': {'dur': 3.6, 'rot': {
      'wingL0': [(0, (0, 0, -6*D)), (1.8, (0, 0, 7*D)), (3.6, (0, 0, -6*D))],
      'wingR0': [(0, (0, 0, 6*D)), (1.8, (0, 0, -7*D)), (3.6, (0, 0, 6*D))],
      'wingL1': [(0, (0, 0, -9*D)), (1.8, (0, 0, 10*D)), (3.6, (0, 0, -9*D))],
      'wingR1': [(0, (0, 0, 9*D)), (1.8, (0, 0, -10*D)), (3.6, (0, 0, 9*D))],
      'neck1': [(0, (0, 3*D, 0)), (1.8, (0, -3*D, 0)), (3.6, (0, 3*D, 0))],
      'head':  [(0, (2*D, -4*D, 0)), (1.8, (2*D, 4*D, 0)), (3.6, (2*D, -4*D, 0))],
      'chest': [(0, (1.5*D, 0, 0)), (0.9, (3.5*D, 0, 0)), (1.8, (1.5*D, 0, 0)), (2.7, (3.5*D, 0, 0)), (3.6, (1.5*D, 0, 0))],
      'tail1': [(0, (0, 10*D, 0)), (1.8, (0, -10*D, 0)), (3.6, (0, 10*D, 0))],
      'tail2': [(0, (0, 14*D, 0)), (1.8, (0, -14*D, 0)), (3.6, (0, 14*D, 0))],
      'tail3': [(0, (0, 18*D, 0)), (1.8, (0, -18*D, 0)), (3.6, (0, 18*D, 0))],
  }},
  'flap': {'dur': 0.9, 'rot': {
      'wingL0': [(0, (0, 0, -34*D)), (0.45, (0, 0, 30*D)), (0.9, (0, 0, -34*D))],
      'wingR0': [(0, (0, 0, 34*D)), (0.45, (0, 0, -30*D)), (0.9, (0, 0, 34*D))],
      'wingL1': [(0, (0, 0, -18*D)), (0.45, (0, 0, 44*D)), (0.9, (0, 0, -18*D))],
      'wingR1': [(0, (0, 0, 18*D)), (0.45, (0, 0, -44*D)), (0.9, (0, 0, 18*D))],
      'wingL2': [(0, (0, 0, -8*D)), (0.45, (0, 0, 26*D)), (0.9, (0, 0, -8*D))],
      'wingR2': [(0, (0, 0, 8*D)), (0.45, (0, 0, -26*D)), (0.9, (0, 0, 8*D))],
      'legFL0': [(0, (26*D, 0, 0)), (0.9, (26*D, 0, 0))],
      'legFR0': [(0, (26*D, 0, 0)), (0.9, (26*D, 0, 0))],
      'legHL0': [(0, (-20*D, 0, 0)), (0.9, (-20*D, 0, 0))],
      'legHR0': [(0, (-20*D, 0, 0)), (0.9, (-20*D, 0, 0))],
      'legFL1': [(0, (30*D, 0, 0)), (0.9, (30*D, 0, 0))],
      'legFR1': [(0, (30*D, 0, 0)), (0.9, (30*D, 0, 0))],
      'legHL1': [(0, (30*D, 0, 0)), (0.9, (30*D, 0, 0))],
      'legHR1': [(0, (30*D, 0, 0)), (0.9, (30*D, 0, 0))],
      'tail1': [(0, (0, 8*D, 0)), (0.45, (0, -8*D, 0)), (0.9, (0, 8*D, 0))],
      'tail2': [(0, (0, 12*D, 0)), (0.45, (0, -12*D, 0)), (0.9, (0, 12*D, 0))],
      'neck1': [(0, (-4*D, 0, 0)), (0.45, (2*D, 0, 0)), (0.9, (-4*D, 0, 0))],
  }},
  'breath': {'dur': 2.6, 'rot': {
      'neck1': [(0, (0, 0, 0)), (0.45, (11*D, 0, 0)), (2.1, (11*D, 0, 0)), (2.6, (0, 0, 0))],
      'neck2': [(0, (0, 0, 0)), (0.45, (13*D, 0, 0)), (2.1, (13*D, 0, 0)), (2.6, (0, 0, 0))],
      'head':  [(0, (0, 0, 0)), (0.45, (20*D, 0, 0)), (0.8, (23*D, 0, 0)), (1.2, (20*D, 0, 0)), (1.6, (23*D, 0, 0)), (2.1, (20*D, 0, 0)), (2.6, (0, 0, 0))],
      'chest': [(0, (0, 0, 0)), (0.5, (-4*D, 0, 0)), (2.1, (-4*D, 0, 0)), (2.6, (0, 0, 0))],
      'wingL0': [(0, (0, 0, -6*D)), (0.6, (0, -14*D, -16*D)), (2.1, (0, -14*D, -16*D)), (2.6, (0, 0, -6*D))],
      'wingR0': [(0, (0, 0, 6*D)), (0.6, (0, 14*D, 16*D)), (2.1, (0, 14*D, 16*D)), (2.6, (0, 0, 6*D))],
      'tail1': [(0, (0, 6*D, 0)), (1.3, (0, -6*D, 0)), (2.6, (0, 6*D, 0))],
      'tail2': [(0, (0, 9*D, 0)), (1.3, (0, -9*D, 0)), (2.6, (0, 9*D, 0))],
  }},
  'bite': {'dur': 0.7, 'rot': {
      'neck1': [(0, (0, 0, 0)), (0.16, (-8*D, 0, 0)), (0.30, (16*D, 0, 0)), (0.55, (4*D, 0, 0)), (0.7, (0, 0, 0))],
      'neck2': [(0, (0, 0, 0)), (0.16, (-6*D, 0, 0)), (0.30, (20*D, 0, 0)), (0.55, (5*D, 0, 0)), (0.7, (0, 0, 0))],
      'head':  [(0, (0, 0, 0)), (0.16, (-10*D, 0, 0)), (0.30, (30*D, 0, 0)), (0.55, (6*D, 0, 0)), (0.7, (0, 0, 0))],
      'chest': [(0, (0, 0, 0)), (0.30, (6*D, 0, 0)), (0.7, (0, 0, 0))],
  }, 'trans': {
      'root': [(0, (0, 0, 0)), (0.16, (0, 0, -0.012)), (0.30, (0, 0, 0.05)), (0.55, (0, 0, 0.012)), (0.7, (0, 0, 0))],
  }},
  'sweep': {'dur': 0.85, 'rot': {
      'root':  [(0, (0, 0, 0)), (0.25, (0, -16*D, 0)), (0.5, (0, 30*D, 0)), (0.85, (0, 0, 0))],
      'tail0': [(0, (0, 0, 0)), (0.30, (0, -14*D, 0)), (0.58, (0, 34*D, 0)), (0.85, (0, 0, 0))],
      'tail1': [(0, (0, 0, 0)), (0.36, (0, -18*D, 0)), (0.64, (0, 40*D, 0)), (0.85, (0, 0, 0))],
      'tail2': [(0, (0, 0, 0)), (0.42, (0, -20*D, 0)), (0.70, (0, 44*D, 0)), (0.85, (0, 0, 0))],
      'tail3': [(0, (0, 0, 0)), (0.48, (0, -22*D, 0)), (0.76, (0, 48*D, 0)), (0.85, (0, 0, 0))],
      'wingL0': [(0, (0, 0, -6*D)), (0.4, (0, 0, -22*D)), (0.85, (0, 0, -6*D))],
      'wingR0': [(0, (0, 0, 6*D)), (0.4, (0, 0, 22*D)), (0.85, (0, 0, 6*D))],
      'head':  [(0, (0, 0, 0)), (0.4, (0, -24*D, 0)), (0.85, (0, 0, 0))],
  }},
  'roar': {'dur': 1.5, 'rot': {
      'neck1': [(0, (0, 0, 0)), (0.4, (-10*D, 0, 0)), (1.1, (-10*D, 0, 0)), (1.5, (0, 0, 0))],
      'neck2': [(0, (0, 0, 0)), (0.4, (-8*D, 0, 0)), (1.1, (-8*D, 0, 0)), (1.5, (0, 0, 0))],
      'head':  [(0, (0, 0, 0)), (0.4, (-24*D, 0, 0)), (1.1, (-24*D, 0, 0)), (1.5, (0, 0, 0))],
      'wingL0': [(0, (0, 0, -6*D)), (0.4, (0, 0, -38*D)), (1.1, (0, 0, -38*D)), (1.5, (0, 0, -6*D))],
      'wingR0': [(0, (0, 0, 6*D)), (0.4, (0, 0, 38*D)), (1.1, (0, 0, 38*D)), (1.5, (0, 0, 6*D))],
      'wingL1': [(0, (0, 0, -9*D)), (0.4, (0, 0, -30*D)), (1.1, (0, 0, -30*D)), (1.5, (0, 0, -9*D))],
      'wingR1': [(0, (0, 0, 9*D)), (0.4, (0, 0, 30*D)), (1.1, (0, 0, 30*D)), (1.5, (0, 0, 9*D))],
      'chest': [(0, (0, 0, 0)), (0.4, (-5*D, 0, 0)), (1.1, (-5*D, 0, 0)), (1.5, (0, 0, 0))],
      'tail1': [(0, (0, 10*D, 0)), (0.75, (0, -10*D, 0)), (1.5, (0, 10*D, 0))],
      'tail2': [(0, (0, 14*D, 0)), (0.75, (0, -14*D, 0)), (1.5, (0, 14*D, 0))],
  }, 'trans': {
      'root': [(0, (0, 0, 0)), (0.4, (0, 0.02, 0)), (1.1, (0, 0.02, 0)), (1.5, (0, 0, 0))],
  }},
  'hurt': {'dur': 0.35, 'rot': {
      'spine': [(0, (0, 0, 0)), (0.08, (-8*D, 0, 0)), (0.35, (0, 0, 0))],
      'head':  [(0, (0, 0, 0)), (0.08, (0, 14*D, 0)), (0.18, (0, -10*D, 0)), (0.35, (0, 0, 0))],
      'neck1': [(0, (0, 0, 0)), (0.08, (-6*D, 0, 0)), (0.35, (0, 0, 0))],
  }},
  'death': {'dur': 1.4, 'rot': {
      'root':  [(0, (0, 0, 0)), (0.7, (4*D, 0, 26*D)), (1.1, (6*D, 0, 38*D)), (1.4, (6*D, 0, 40*D))],
      'neck1': [(0, (0, 0, 0)), (0.9, (16*D, 0, 6*D)), (1.4, (20*D, 0, 8*D))],
      'neck2': [(0, (0, 0, 0)), (0.9, (18*D, 0, 6*D)), (1.4, (22*D, 0, 8*D))],
      'head':  [(0, (0, 0, 0)), (0.9, (14*D, 10*D, 10*D)), (1.4, (16*D, 12*D, 12*D))],
      'wingL0': [(0, (0, 0, -6*D)), (1.0, (0, 0, 26*D)), (1.4, (0, 0, 30*D))],
      'wingR0': [(0, (0, 0, 6*D)), (1.0, (0, 0, 20*D)), (1.4, (0, 0, 24*D))],
      'wingL1': [(0, (0, 0, -9*D)), (1.0, (0, 0, 22*D)), (1.4, (0, 0, 26*D))],
      'wingR1': [(0, (0, 0, 9*D)), (1.0, (0, 0, 18*D)), (1.4, (0, 0, 22*D))],
      'tail1': [(0, (0, 10*D, 0)), (1.4, (0, 4*D, 0))],
      'tail2': [(0, (0, 14*D, 0)), (1.4, (0, 6*D, 0))],
  }, 'trans': {
      'root': [(0, (0, 0, 0)), (0.7, (0, -0.05, 0)), (1.1, (0, -0.085, 0)), (1.4, (0, -0.09, 0))],
  }},
}

# ---------- 组装 GLB ----------
bin_parts = []; bvs = []; offset = 0
def add_bv(data, target=None):
    global offset
    pad = (4 - offset % 4) % 4
    if pad: bin_parts.append(b'\0' * pad); offset += pad
    bv = {'buffer': 0, 'byteOffset': offset, 'byteLength': len(data)}
    if target: bv['target'] = target
    bvs.append(bv); bin_parts.append(data); offset += len(data)
    return len(bvs) - 1

b_img = [add_bv(im) for im in img_bytes]
b_pos = add_bv(pos.tobytes(), 34962)
b_nor = add_bv(nor.tobytes(), 34962)
b_uv = add_bv(uv.tobytes(), 34962)
b_jnt = add_bv(joints.tobytes(), 34962)
b_wgt = add_bv(weights.tobytes(), 34962)
b_idx = add_bv(idx.tobytes(), 34963)
ibm = array.array('f')
for n in ORDER:
    x, y, z = WORLD[n]
    ibm.extend([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -x, -y, -z, 1])
b_ibm = add_bv(ibm.tobytes())

accessors = [
    {'bufferView': b_pos, 'componentType': 5126, 'count': NV, 'type': 'VEC3',
     'min': [min(pos[0::3]), min(pos[1::3]), min(pos[2::3])], 'max': [max(pos[0::3]), max(pos[1::3]), max(pos[2::3])]},
    {'bufferView': b_nor, 'componentType': 5126, 'count': NV, 'type': 'VEC3'},
    {'bufferView': b_uv, 'componentType': 5126, 'count': NV, 'type': 'VEC2'},
    {'bufferView': b_jnt, 'componentType': 5121, 'count': NV, 'type': 'VEC4'},
    {'bufferView': b_wgt, 'componentType': 5126, 'count': NV, 'type': 'VEC4'},
    {'bufferView': b_idx, 'componentType': 5125, 'count': len(idx), 'type': 'SCALAR'},
    {'bufferView': b_ibm, 'componentType': 5126, 'count': len(ORDER), 'type': 'MAT4'},
]
ACC_IBM = 6

animations = []
for clip_name, clip in CLIPS.items():
    samplers = []; channels = []
    def add_channel(bone, path, keys):
        times = array.array('f', [k[0] for k in keys])
        vals = array.array('f')
        if path == 'rotation':
            for _, e in keys: vals.extend(q_euler(*e))
            vtype = 'VEC4'
        else:
            for _, v in keys: vals.extend(v)
            vtype = 'VEC3'
        b_t = add_bv(times.tobytes()); b_v = add_bv(vals.tobytes())
        accessors.append({'bufferView': b_t, 'componentType': 5126, 'count': len(keys), 'type': 'SCALAR', 'min': [min(times)], 'max': [max(times)]})
        accessors.append({'bufferView': b_v, 'componentType': 5126, 'count': len(keys), 'type': vtype})
        samplers.append({'input': len(accessors) - 2, 'output': len(accessors) - 1, 'interpolation': 'LINEAR'})
        channels.append({'sampler': len(samplers) - 1, 'target': {'node': 1 + BIDX[bone], 'path': path}})
    for bone, keys in clip.get('rot', {}).items(): add_channel(bone, 'rotation', keys)
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
    if CHILDREN[n]: node['children'] = [1 + BIDX[c] for c in CHILDREN[n]]
    nodes.append(node)

new_g = {
    'asset': {'version': '2.0', 'generator': 'DragonKnight dragon rig pipeline'},
    'scene': 0, 'scenes': [{'nodes': [0, 1]}],
    'nodes': nodes,
    'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2, 'JOINTS_0': 3, 'WEIGHTS_0': 4}, 'indices': 5, 'material': 0}]}],
    'materials': g['materials'],
    'textures': g['textures'],
    'samplers': g.get('samplers', []),
    'images': [{'bufferView': b_img[i], 'mimeType': g['images'][i].get('mimeType', 'image/webp')} for i in range(len(img_bytes))],
    'bufferViews': bvs,
    'accessors': accessors,
    'skins': [{'joints': [1 + i for i in range(len(ORDER))], 'inverseBindMatrices': ACC_IBM, 'skeleton': 1}],
    'animations': animations,
    'buffers': [{'byteLength': offset}],
}
jb = json.dumps(new_g).encode(); jb += b' ' * ((4 - len(jb) % 4) % 4)
binb = b''.join(bin_parts); binb += b'\0' * ((4 - len(binb) % 4) % 4)
total = 12 + 8 + len(jb) + 8 + len(binb)
out = struct.pack('<III', 0x46546C67, 2, total) + struct.pack('<II', len(jb), 0x4E4F534A) + jb + struct.pack('<II', len(binb), 0x004E4942) + binb
open(DST, 'wb').write(out)
print(DST, 'MB:', round(len(out) / 1e6, 2), '| bones:', len(ORDER), '| clips:', [a['name'] for a in animations])
