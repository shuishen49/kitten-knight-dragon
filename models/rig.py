#!/usr/bin/env python3
"""给 cat2.glb 绑骨骼 + 烘焙动画，输出 cat-anim.glb。
坐标系：glTF/three 空间，Y 上，+Z 朝前（脸朝向），剑在 -X（右爪），盾在 +X（左爪）。
静止姿态所有关节旋转为单位四元数 -> IBM 只是平移取负，蒙皮数学简单可靠。
权重：顶点到骨骼线段的距离衰减 + 道具（剑/盾/尾巴）区域硬分配。"""
import struct, json, array, math

SRC = 'cat2.glb'
DST = 'cat-anim.glb'

# ---------- 读源 GLB ----------
d = open(SRC, 'rb').read()
jlen = struct.unpack('<I', d[12:16])[0]
g = json.loads(d[20:20 + jlen])
bin_chunk = 20 + jlen + 8
prim = g['meshes'][0]['primitives'][0]
def acc_bytes(ai):
    acc = g['accessors'][ai]; bv = g['bufferViews'][acc['bufferView']]
    return bin_chunk + bv.get('byteOffset', 0) + acc.get('byteOffset', 0), acc
ps, pacc = acc_bytes(prim['attributes']['POSITION'])
NV = pacc['count']
pos = array.array('f'); pos.frombytes(d[ps:ps + NV * 12])
ns, nacc = acc_bytes(prim['attributes']['NORMAL'])
nor = array.array('f'); nor.frombytes(d[ns:ns + NV * 12])
ts, tacc = acc_bytes(prim['attributes']['TEXCOORD_0'])
uv = array.array('f'); uv.frombytes(d[ts:ts + NV * 8])
is_, iacc = acc_bytes(prim['indices'])
itype = 'H' if iacc['componentType'] == 5123 else 'I'
idx = array.array(itype); idx.frombytes(d[is_:is_ + iacc['count'] * (2 if itype == 'H' else 4)])
idx = array.array('I', idx.tolist())
P = [(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]) for i in range(NV)]

# ---------- 骨架定义（世界位置，父级，静止旋转=0） ----------
# name: (parent, world_pos)
BONES = {
    'root':      (None,        (0.0, 0.40, 0.0)),
    'hips':      ('root',      (0.0, 0.30, 0.0)),
    'spine':     ('hips',      (0.0, 0.40, 0.0)),
    'chest':     ('spine',     (0.0, 0.47, 0.0)),
    'head':      ('chest',     (0.0, 0.55, 0.0)),
    'shoulderR': ('chest',     (-0.15, 0.485, 0.0)),
    'elbowR':    ('shoulderR', (-0.235, 0.385, 0.02)),
    'handR':     ('elbowR',    (-0.26, 0.29, 0.06)),
    'shoulderL': ('chest',     (0.15, 0.485, 0.0)),
    'elbowL':    ('shoulderL', (0.24, 0.39, 0.03)),
    'handL':     ('elbowL',    (0.275, 0.315, 0.10)),
    'legR':      ('hips',      (-0.09, 0.27, 0.0)),
    'kneeR':     ('legR',      (-0.10, 0.14, 0.005)),
    'footR':     ('kneeR',     (-0.10, 0.02, 0.03)),
    'legL':      ('hips',      (0.09, 0.27, 0.0)),
    'kneeL':     ('legL',      (0.10, 0.14, 0.005)),
    'footL':     ('kneeL',     (0.10, 0.02, 0.03)),
    'tail1':     ('hips',      (0.0, 0.27, -0.11)),
    'tail2':     ('tail1',     (0.0, 0.235, -0.225)),
    'tail3':     ('tail2',     (0.0, 0.27, -0.325)),
}
ORDER = list(BONES.keys())
BIDX = {n: i for i, n in enumerate(ORDER)}
WORLD = {n: BONES[n][1] for n in ORDER}
PARENT = {n: BONES[n][0] for n in ORDER}
CHILDREN = {n: [] for n in ORDER}
for n in ORDER:
    if PARENT[n]: CHILDREN[PARENT[n]].append(n)
# 蒙皮线段（骨骼关节 -> 子关节；末端骨用自身小段）
def seg_of(name):
    p = WORLD[name]
    if CHILDREN[name]:
        # 主线段取第一个子骨（手/脚/尾巴尖再延长）
        c = WORLD[CHILDREN[name][0]]
        return (p, c)
    return (p, p)
SEG = {n: seg_of(n) for n in ORDER}
# 道具伪线段：剑（handR 沿剑刃向上）、盾（handL 到盾心）
SEG['handR'] = (WORLD['handR'], (-0.29, 0.92, 0.10))
SEG['handL'] = (WORLD['handL'], (0.315, 0.44, 0.20))

# ---------- 权重计算 ----------
def dist_seg(p, a, b):
    ax, ay, az = a; bx, by, bz = b; px, py, pz = p
    dx, dy, dz = bx - ax, by - ay, bz - az
    L2 = dx * dx + dy * dy + dz * dz
    if L2 < 1e-9: t = 0.0
    else: t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy + (pz - az) * dz) / L2))
    cx, cy, cz = ax + t * dx, ay + t * dy, az + t * dz
    return math.sqrt((px - cx) ** 2 + (py - cy) ** 2 + (pz - cz) ** 2)

# 每根骨的影响半径（衰减尺度）
RAD = {'root': 0.30, 'hips': 0.17, 'spine': 0.15, 'chest': 0.16, 'head': 0.30,
       'shoulderR': 0.075, 'elbowR': 0.07, 'handR': 0.16,
       'shoulderL': 0.075, 'elbowL': 0.07, 'handL': 0.17,
       'legR': 0.085, 'kneeR': 0.08, 'footR': 0.07,
       'legL': 0.085, 'kneeL': 0.08, 'footL': 0.07,
       'tail1': 0.075, 'tail2': 0.07, 'tail3': 0.075}

joints = array.array('B')   # ubyte x4 per vert
weights = array.array('f')
HEAD_C = (0.0, 0.74, 0.02)
SHIELD_C = (0.30, 0.45, 0.16)
BLADE_A = WORLD['handR']; BLADE_B = (-0.29, 0.92, 0.10)
def vdist(a, b): return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)
for i in range(NV):
    p = P[i]; x, y, z = p
    # 规则池（优先级从高到低）
    if dist_seg(p, BLADE_A, BLADE_B) < 0.038 and x < -0.15:
        pool = ['handR']                                        # 剑刃：细管刚性
    elif vdist(p, HEAD_C) < 0.34:
        pool = ['head', 'chest']                                # 头（含耳朵/蝴蝶结/脸颊）
    elif vdist(p, SHIELD_C) < 0.225:
        pool = ['handL', 'elbowL']                              # 盾盘（整盘同池，内沿也不许逃）
    elif z < -0.13 and y < 0.36 and abs(x) < 0.16:
        pool = ['tail1', 'tail2', 'tail3', 'hips']              # 尾巴
    elif x < -0.185 and y > 0.30:
        pool = ['handR', 'elbowR', 'shoulderR']                 # 右臂外侧（剑柄/护手）
    elif x > 0.185 and 0.26 < y < 0.70:
        pool = ['handL', 'elbowL', 'shoulderL']                 # 左臂外侧
    elif y > 0.50:
        pool = ['head', 'chest', 'spine']
    elif y < 0.30:
        pool = ['legR', 'kneeR', 'footR', 'legL', 'kneeL', 'footL', 'hips', 'tail1']
    elif abs(x) > 0.13 and y < 0.56:
        pool = ['shoulderR', 'elbowR', 'shoulderL', 'elbowL', 'chest'] if x < 0 else ['shoulderL', 'elbowL', 'shoulderR', 'elbowR', 'chest']
    else:
        pool = ['hips', 'spine', 'chest', 'shoulderR', 'shoulderL']
    cand = []
    for bn in pool:
        dd = dist_seg(p, *SEG[bn])
        r = RAD[bn]
        w = math.exp(-(dd * dd) / (2 * r * r))
        cand.append((w, bn))
    cand.sort(reverse=True)
    top = cand[:4]
    ssum = sum(w for w, _ in top) or 1.0
    js = [BIDX[bn] for _, bn in top] + [0] * (4 - len(top))
    ws = [w / ssum for w, _ in top] + [0.0] * (4 - len(top))
    joints.extend(js); weights.extend(ws)
print('weights done')

# ---------- 四元数工具（Euler XYZ, three 惯例 q = qx*qy*qz 的逆序合成与 three 一致即可保证自洽） ----------
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

# ---------- 动画定义 ----------
# 每个 clip: {bone: [(t, (rx,ry,rz)), ...]}, trans: {bone: [(t, (x,y,z) 相对静止偏移), ...]}
D = math.pi / 180
CLIPS = {
  'idle': {'dur': 2.4, 'rot': {
      'spine': [(0, (1.5*D, 0, 0)), (1.2, (3.5*D, 0, 0)), (2.4, (1.5*D, 0, 0))],
      'head':  [(0, (0, -4*D, 1.5*D)), (1.2, (0, 4*D, -1.5*D)), (2.4, (0, -4*D, 1.5*D))],
      'tail1': [(0, (0, 14*D, 0)), (1.2, (0, -14*D, 0)), (2.4, (0, 14*D, 0))],
      'tail2': [(0, (0, 18*D, 0)), (1.2, (0, -18*D, 0)), (2.4, (0, 18*D, 0))],
      'tail3': [(0, (0, 22*D, 0)), (1.2, (0, -22*D, 0)), (2.4, (0, 22*D, 0))],
      'shoulderR': [(0, (3*D, 0, -2*D)), (1.2, (6*D, 0, -2*D)), (2.4, (3*D, 0, -2*D))],
      'shoulderL': [(0, (3*D, 0, 2*D)), (1.2, (6*D, 0, 2*D)), (2.4, (3*D, 0, 2*D))],
  }},
  'walk': {'dur': 0.8, 'rot': {
      'legR':  [(0, (26*D, 0, 0)), (0.4, (-26*D, 0, 0)), (0.8, (26*D, 0, 0))],
      'legL':  [(0, (-26*D, 0, 0)), (0.4, (26*D, 0, 0)), (0.8, (-26*D, 0, 0))],
      'kneeR': [(0, (8*D, 0, 0)), (0.2, (30*D, 0, 0)), (0.4, (8*D, 0, 0)), (0.6, (4*D, 0, 0)), (0.8, (8*D, 0, 0))],
      'kneeL': [(0, (8*D, 0, 0)), (0.2, (4*D, 0, 0)), (0.4, (8*D, 0, 0)), (0.6, (30*D, 0, 0)), (0.8, (8*D, 0, 0))],
      'shoulderR': [(0, (-16*D, 0, -3*D)), (0.4, (16*D, 0, -3*D)), (0.8, (-16*D, 0, -3*D))],
      'shoulderL': [(0, (16*D, 0, 3*D)), (0.4, (-16*D, 0, 3*D)), (0.8, (16*D, 0, 3*D))],
      'head':  [(0, (0, 0, 2*D)), (0.4, (0, 0, -2*D)), (0.8, (0, 0, 2*D))],
      'tail1': [(0, (0, 16*D, 0)), (0.4, (0, -16*D, 0)), (0.8, (0, 16*D, 0))],
      'tail2': [(0, (0, 20*D, 0)), (0.4, (0, -20*D, 0)), (0.8, (0, 20*D, 0))],
  }, 'trans': {
      'hips': [(0, (0, 0.012, 0)), (0.2, (0, -0.008, 0)), (0.4, (0, 0.012, 0)), (0.6, (0, -0.008, 0)), (0.8, (0, 0.012, 0))],
  }},
  'slash': {'dur': 0.45, 'rot': {
      'shoulderR': [(0, (0, 0, 0)), (0.14, (-125*D, 0, -18*D)), (0.24, (95*D, 0, 10*D)), (0.45, (0, 0, 0))],
      'elbowR':    [(0, (-8*D, 0, 0)), (0.14, (-38*D, 0, 0)), (0.24, (-4*D, 0, 0)), (0.45, (-8*D, 0, 0))],
      'spine':     [(0, (0, 0, 0)), (0.14, (0, 16*D, 0)), (0.24, (6*D, -20*D, 0)), (0.45, (0, 0, 0))],
      'chest':     [(0, (0, 0, 0)), (0.14, (-6*D, 10*D, 0)), (0.24, (16*D, -12*D, 0)), (0.45, (0, 0, 0))],
      'head':      [(0, (0, 0, 0)), (0.14, (0, -10*D, 0)), (0.24, (0, 8*D, 0)), (0.45, (0, 0, 0))],
      'shoulderL': [(0, (0, 0, 0)), (0.14, (10*D, 0, 8*D)), (0.24, (26*D, 0, 14*D)), (0.45, (0, 0, 0))],
  }},
  'roll': {'dur': 0.5, 'rot': {
      'root':  [(0, (0, 0, 0)), (0.125, (95*D, 0, 0)), (0.25, (185*D, 0, 0)), (0.375, (272*D, 0, 0)), (0.5, (360*D, 0, 0))],
      'spine': [(0, (0, 0, 0)), (0.1, (34*D, 0, 0)), (0.3, (40*D, 0, 0)), (0.5, (0, 0, 0))],
      'head':  [(0, (0, 0, 0)), (0.1, (30*D, 0, 0)), (0.3, (34*D, 0, 0)), (0.5, (0, 0, 0))],
      'legR':  [(0, (0, 0, 0)), (0.1, (38*D, 0, 0)), (0.35, (38*D, 0, 0)), (0.5, (0, 0, 0))],
      'legL':  [(0, (0, 0, 0)), (0.1, (38*D, 0, 0)), (0.35, (38*D, 0, 0)), (0.5, (0, 0, 0))],
      'kneeR': [(0, (0, 0, 0)), (0.1, (44*D, 0, 0)), (0.35, (44*D, 0, 0)), (0.5, (0, 0, 0))],
      'kneeL': [(0, (0, 0, 0)), (0.1, (44*D, 0, 0)), (0.35, (44*D, 0, 0)), (0.5, (0, 0, 0))],
      'shoulderR': [(0, (0, 0, 0)), (0.1, (42*D, 0, -14*D)), (0.35, (42*D, 0, -14*D)), (0.5, (0, 0, 0))],
      'shoulderL': [(0, (0, 0, 0)), (0.1, (42*D, 0, 14*D)), (0.35, (42*D, 0, 14*D)), (0.5, (0, 0, 0))],
  }, 'trans': {
      'root': [(0, (0, 0, 0)), (0.125, (0, 0.07, 0)), (0.25, (0, 0.19, 0)), (0.375, (0, 0.07, 0)), (0.5, (0, 0, 0))],
  }},
  'jump': {'dur': 0.6, 'rot': {
      'legR':  [(0, (0, 0, 0)), (0.12, (30*D, 0, 0)), (0.26, (-24*D, 0, 0)), (0.42, (10*D, 0, 0)), (0.52, (30*D, 0, 0)), (0.6, (0, 0, 0))],
      'legL':  [(0, (0, 0, 0)), (0.12, (30*D, 0, 0)), (0.26, (-24*D, 0, 0)), (0.42, (10*D, 0, 0)), (0.52, (30*D, 0, 0)), (0.6, (0, 0, 0))],
      'kneeR': [(0, (0, 0, 0)), (0.12, (48*D, 0, 0)), (0.26, (12*D, 0, 0)), (0.42, (30*D, 0, 0)), (0.52, (48*D, 0, 0)), (0.6, (0, 0, 0))],
      'kneeL': [(0, (0, 0, 0)), (0.12, (48*D, 0, 0)), (0.26, (12*D, 0, 0)), (0.42, (30*D, 0, 0)), (0.52, (48*D, 0, 0)), (0.6, (0, 0, 0))],
      'shoulderR': [(0, (0, 0, 0)), (0.12, (14*D, 0, -8*D)), (0.26, (-52*D, 0, -22*D)), (0.42, (-30*D, 0, -14*D)), (0.52, (14*D, 0, -8*D)), (0.6, (0, 0, 0))],
      'shoulderL': [(0, (0, 0, 0)), (0.12, (14*D, 0, 8*D)), (0.26, (-52*D, 0, 22*D)), (0.42, (-30*D, 0, 14*D)), (0.52, (14*D, 0, 8*D)), (0.6, (0, 0, 0))],
      'spine': [(0, (0, 0, 0)), (0.12, (16*D, 0, 0)), (0.26, (-8*D, 0, 0)), (0.52, (16*D, 0, 0)), (0.6, (0, 0, 0))],
      'tail1': [(0, (0, 0, 0)), (0.26, (-18*D, 0, 0)), (0.6, (0, 0, 0))],
      'tail2': [(0, (0, 0, 0)), (0.26, (-22*D, 0, 0)), (0.6, (0, 0, 0))],
  }, 'trans': {
      'root': [(0, (0, 0.02, 0)), (0.12, (0, -0.07, 0)), (0.26, (0, 0.10, 0)), (0.42, (0, 0.06, 0)), (0.52, (0, -0.07, 0)), (0.6, (0, 0.02, 0))],
  }},
  'block': {'dur': 0.5, 'rot': {
      'shoulderL': [(0, (0, 0, 0)), (0.12, (18*D, -34*D, 30*D)), (0.5, (18*D, -34*D, 30*D))],
      'elbowL':    [(0, (0, 0, 0)), (0.12, (-24*D, 0, 0)), (0.5, (-24*D, 0, 0))],
      'head':      [(0, (0, 0, 0)), (0.12, (14*D, 0, 0)), (0.5, (14*D, 0, 0))],
      'spine':     [(0, (0, 0, 0)), (0.12, (10*D, 0, 0)), (0.5, (10*D, 0, 0))],
      'shoulderR': [(0, (0, 0, 0)), (0.12, (20*D, 0, -16*D)), (0.5, (20*D, 0, -16*D))],
  }, 'trans': {
      'root': [(0, (0, 0.02, 0)), (0.12, (0, -0.03, 0)), (0.5, (0, -0.03, 0))],
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

src_imgs = [open(f'tex2_{i}.webp', 'rb').read() for i in range(3)]
b_img = [add_bv(im) for im in src_imgs]
b_pos = add_bv(pos.tobytes(), 34962)
b_nor = add_bv(nor.tobytes(), 34962)
b_uv = add_bv(uv.tobytes(), 34962)
b_jnt = add_bv(joints.tobytes(), 34962)
b_wgt = add_bv(weights.tobytes(), 34962)
b_idx = add_bv(idx.tobytes(), 34963)
# IBM：静止全是纯平移，逆矩阵 = 平移取负（列主序 4x4）
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

# 动画通道数据
animations = []
for clip_name, clip in CLIPS.items():
    samplers = []; channels = []
    def add_channel(bone, path, keys):
        times = array.array('f', [k[0] for k in keys])
        if path == 'rotation':
            vals = array.array('f')
            for _, e in keys: vals.extend(q_euler(*e))
            vtype, ctype = 'VEC4', 5126
        else:
            vals = array.array('f')
            for _, v in keys: vals.extend(v)
            vtype, ctype = 'VEC3', 5126
        b_t = add_bv(times.tobytes()); b_v = add_bv(vals.tobytes())
        tmin, tmax = min(times), max(times)
        accessors.append({'bufferView': b_t, 'componentType': 5126, 'count': len(keys), 'type': 'SCALAR', 'min': [tmin], 'max': [tmax]})
        accessors.append({'bufferView': b_v, 'componentType': ctype, 'count': len(keys), 'type': vtype})
        samplers.append({'input': len(accessors) - 2, 'output': len(accessors) - 1, 'interpolation': 'LINEAR'})
        channels.append({'sampler': len(samplers) - 1, 'target': {'node': 1 + BIDX[bone], 'path': path}})
    for bone, keys in clip.get('rot', {}).items(): add_channel(bone, 'rotation', keys)
    for bone, keys in clip.get('trans', {}).items():
        # 平移关键帧给的是相对静止位置的偏移，通道需要绝对局部平移
        base = [0, 0, 0]
        par = PARENT[bone]
        if par: base = [WORLD[bone][i] - WORLD[par][i] for i in range(3)]
        else: base = list(WORLD[bone])
        abs_keys = [(t, (base[0] + v[0], base[1] + v[1], base[2] + v[2])) for t, v in keys]
        add_channel(bone, 'translation', abs_keys)
    animations.append({'name': clip_name, 'samplers': samplers, 'channels': channels})

# 节点：0=网格，1..=关节
nodes = [{'mesh': 0, 'skin': 0, 'name': 'cat-knight-rigged'}]
for n in ORDER:
    par = PARENT[n]
    loc = WORLD[n] if par is None else tuple(WORLD[n][i] - WORLD[par][i] for i in range(3))
    node = {'name': n, 'translation': list(loc)}
    if CHILDREN[n]: node['children'] = [1 + BIDX[c] for c in CHILDREN[n]]
    nodes.append(node)

new_g = {
    'asset': {'version': '2.0', 'generator': 'DragonKnight rig pipeline (bones + baked clips)'},
    'scene': 0, 'scenes': [{'nodes': [0, 1]}],
    'nodes': nodes,
    'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2, 'JOINTS_0': 3, 'WEIGHTS_0': 4}, 'indices': 5, 'material': 0}]}],
    'materials': [g['materials'][0]],
    'textures': [{'sampler': 0, 'source': 0}, {'sampler': 0, 'source': 1}, {'sampler': 0, 'source': 2}],
    'samplers': g.get('samplers', []),
    'images': [{'bufferView': b_img[0], 'mimeType': 'image/webp'}, {'bufferView': b_img[1], 'mimeType': 'image/webp'}, {'bufferView': b_img[2], 'mimeType': 'image/webp'}],
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
