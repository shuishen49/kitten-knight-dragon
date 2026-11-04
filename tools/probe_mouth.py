#!/usr/bin/env python3
"""探测吻部/下颌几何与头部壳层划分，用于放置下颌骨骼。

模型空间：Y 上、+Z 朝脸。头部骨骼在 (0.01, 0.40, 0.225)。
"""
import sys
import numpy as np
sys.path.insert(0, "tools")
import rigview as rv

r = rv.Rig()
nv = len(r.P)
tri = r.I.reshape(-1, 3)
e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
e = np.unique(np.sort(e, axis=1), axis=0)
par = np.arange(nv)


def find(x):
    while par[x] != x:
        par[x] = par[par[x]]
        x = par[x]
    return x


for a, b in e:
    ra, rb = find(a), find(b)
    if ra != rb:
        par[ra] = rb
roots = np.array([find(i) for i in range(nv)])

# ---- 吻部横截面：z 切片上的 y 分布（前部 z>0.14） ----
print("== muzzle cross sections (z-slices, all verts) ==")
print(" z-range      n   y[min  mean  max]  |x|max  y-histogram(0.25..0.50)")
for z0 in np.arange(0.10, 0.30, 0.02):
    m = (r.P[:, 2] >= z0) & (r.P[:, 2] < z0 + 0.02)
    S = r.P[m]
    if len(S) == 0:
        continue
    h, _ = np.histogram(S[:, 1], bins=np.arange(0.25, 0.51, 0.01))
    hh = "".join(" .:-=+*#%@"[min(9, int(v / max(1, h.max()) * 9))] for v in h)
    print(" %.2f-%.2f %5d  %.3f %.3f %.3f  %.3f  %s" % (
        z0, z0 + 0.02, len(S), S[:, 1].min(), S[:, 1].mean(), S[:, 1].max(), np.abs(S[:, 0]).max(), hh))
print("（y 轴从左 0.25 到右 0.50）")

# ---- 头部区域内的连通壳层 ----
head = (r.P[:, 1] > 0.27) & (r.P[:, 2] > 0.10)
print("\n== shells with any vertex in head box (y>0.27, z>0.10), top 16 by size ==")
uid = np.unique(roots[head])
rows = []
for u in uid:
    m = roots == u
    S = r.P[m]
    rows.append((int(m.sum()), u, S))
rows.sort(reverse=True, key=lambda t: t[0])
for cnt, u, S in rows[:16]:
    cz = S[:, 2].mean()
    print("  %5d verts  x[%6.3f,%6.3f] y[%6.3f,%6.3f] z[%6.3f,%6.3f]  mean z %.3f" % (
        cnt, S[:, 0].min(), S[:, 0].max(), S[:, 1].min(), S[:, 1].max(), S[:, 2].min(), S[:, 2].max(), cz))
print("total shells touching head box:", len(rows))

# ---- 候选下颌顶点：头前部、口线以下 ----
for yline in (0.33, 0.34, 0.35, 0.36):
    m = (r.P[:, 2] > 0.16) & (r.P[:, 1] < yline) & (r.P[:, 1] > 0.27)
    S = r.P[m]
    print("jaw候选 y<%.2f & z>0.16: %5d verts  bbox x[%.3f,%.3f] y[%.3f,%.3f] z[%.3f,%.3f]  shells %d" % (
        yline, m.sum(), S[:, 0].min(), S[:, 0].max(), S[:, 1].min(), S[:, 1].max(),
        S[:, 2].min(), S[:, 2].max(), len(np.unique(roots[m]))))
