#!/usr/bin/env python3
"""探测黑龙网格拓扑与头部/嘴部几何，用于规划下颌骨骼与权重平滑。"""
import sys
import numpy as np
sys.path.insert(0, "tools")
import rigview as rv

r = rv.Rig()
nv = len(r.P)
tri = r.I.reshape(-1, 3)

# --- 拓扑：连通分量 / 平均度数 ---
edges = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
edges = np.unique(np.sort(edges, axis=1), axis=0)
parent = np.arange(nv)


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


for a, b in edges:
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[ra] = rb
roots = np.array([find(i) for i in range(nv)])
uniq, cnt = np.unique(roots, return_counts=True)
print("verts %d  unique edges %d  avg degree %.2f" % (nv, len(edges), 2.0 * len(edges) / nv))
print("connected components: %d" % len(uniq))
if len(uniq) > 1:
    for u, c in sorted(zip(uniq, cnt), key=lambda t: -t[1])[:12]:
        m = roots == u
        P = r.P[m]
        print("  comp verts %6d  bbox x[%6.3f,%6.3f] y[%6.3f,%6.3f] z[%6.3f,%6.3f]" % (
            c, P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max(), P[:, 2].min(), P[:, 2].max()))

# --- 头部区域切片：找吻部/嘴的位置 ---
HC = np.array([0.01, 0.40, 0.225])
d = (r.P - HC) / np.array([0.085, 0.115, 0.08])
head = np.einsum("ij,ij->i", d, d) < 1.0
print("\nhead-ellipsoid verts: %d" % head.sum())
H = r.P[head]
zbins = np.arange(0.12, 0.30, 0.02)
print(" z-slice      n    y[min   mean  max]   |x|max")
for z0 in zbins:
    m = (H[:, 2] >= z0) & (H[:, 2] < z0 + 0.02)
    if m.sum() == 0:
        continue
    S = H[m]
    print("  %.2f-%.2f %5d   %.3f  %.3f  %.3f   %.3f" % (
        z0, z0 + 0.02, m.sum(), S[:, 1].min(), S[:, 1].mean(), S[:, 1].max(), np.abs(S[:, 0]).max()))
print("\nhead bone rest pos:", np.round(r.joint_rest()[r.bone_names.index("head")], 4))

# 头部以外但属于 head 骨骼主导的顶点（评估头部权重是否越界）
dom = np.argmax(r.W, 1)
hi = r.bone_names.index("head")
m = dom == hi
print("head-dominant verts %d  bbox x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f]" % (
    m.sum(), r.P[m, 0].min(), r.P[m, 0].max(), r.P[m, 1].min(), r.P[m, 1].max(), r.P[m, 2].min(), r.P[m, 2].max()))

# 下颌候选：头部区域内、位于头心下方且靠前
cand = head & (r.P[:, 1] < HC[1] - 0.01) & (r.P[:, 2] > HC[2] - 0.02)
C = r.P[cand]
print("jaw candidates (head 区 前下方) verts %d" % cand.sum())
if len(C):
    print("  bbox x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f]" % (
        C[:, 0].min(), C[:, 0].max(), C[:, 1].min(), C[:, 1].max(), C[:, 2].min(), C[:, 2].max()))
