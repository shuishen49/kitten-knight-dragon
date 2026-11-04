#!/usr/bin/env python3
"""头部 X 光图：找嘴线 / 下颌铰链。三张图：
 1) 中剖面 (z,y)  2) 吻部正面 (x,y) 剖切  3) 逐 z 切片的 y 分布 + 空档
所有统计只包含落在切片盒内的点（盒外的点直接丢弃，不剪到边上）。"""
import sys, argparse
import numpy as np
sys.path.insert(0, "tools")
import rigview as rv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ap = argparse.ArgumentParser()
ap.add_argument("--clip", default=None)
ap.add_argument("--time", type=float, default=0.0)
AA = ap.parse_args()
r = rv.Rig()
P = r.P if AA.clip is None else r.skin(AA.clip, AA.time)[0]
print("姿态: %s" % ("静止" if AA.clip is None else "%s t=%.2f" % (AA.clip, AA.time)))
ramp = " .:-=+*#%@"


def box(x0, x1, y0, y1, z0, z1):
    return ((P[:, 0] >= x0) & (P[:, 0] <= x1) & (P[:, 1] >= y0) & (P[:, 1] <= y1)
            & (P[:, 2] >= z0) & (P[:, 2] <= z1))


def grid(mask, ia, ib, alo, ahi, blo, bhi, da, db, title, la, lb):
    S = P[mask]
    if len(S) < 4:
        print("== %s == 切片内不足 4 点" % title)
        return
    na = int(round((ahi - alo) / da)) + 1
    nb = int(round((bhi - blo) / db)) + 1
    cnt = np.zeros((na, nb), int)
    i = np.clip(((S[:, ia] - alo) / da).round().astype(int), 0, na - 1)
    j = np.clip(((S[:, ib] - blo) / db).round().astype(int), 0, nb - 1)
    np.add.at(cnt, (i, j), 1)
    mx = int(cnt.max())
    print("== %s == 切片内 %d 点，单格最多 %d 点" % (title, len(S), mx))
    den = np.log1p(mx)
    for a in range(na - 1, -1, -1):
        row = "".join(ramp[0 if v == 0 else min(9, int(9.0 * np.log1p(v) / den))] for v in cnt[a])
        print("%s%7.3f |%s|" % (la, alo + a * da, row))
    print("       %s 刻度 %.3f 到 %.3f 步长 %.3f（%s 向右）" % (lb, blo, bhi, db, lb))


print("模型空间 bbox: x %.3f..%.3f  y %.3f..%.3f  z %.3f..%.3f" % (
    P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max(), P[:, 2].min(), P[:, 2].max()))

grid(box(-0.03, 0.03, 0.24, 0.50, 0.08, 0.31), 1, 2, 0.24, 0.50, 0.08, 0.31, 0.008, 0.005,
     "中剖面 |x|<0.03：y 对 z", "y", "z")
grid(box(-0.14, 0.14, 0.24, 0.50, 0.18, 0.24), 1, 0, 0.24, 0.50, -0.14, 0.14, 0.008, 0.008,
     "吻部正面剖切 z 0.18-0.24：y 对 x", "y", "x")
grid(box(-0.14, 0.14, 0.24, 0.50, 0.24, 0.30), 1, 0, 0.24, 0.50, -0.14, 0.14, 0.008, 0.008,
     "吻端正面剖切 z 0.24-0.30：y 对 x", "y", "x")

print("\n== 逐 z 切片（|x|<0.12）y 直方图 0.24..0.50 步 0.005，标出空档 ==")
bins = np.arange(0.24, 0.5001, 0.005)
for z0 in np.arange(0.12, 0.30, 0.01):
    m = box(-0.12, 0.12, 0.24, 0.50, z0, z0 + 0.01)
    S = P[m]
    if len(S) < 3:
        continue
    h, _ = np.histogram(S[:, 1], bins=bins)
    hh = "".join(ramp[0 if v == 0 else min(9, int(9.0 * np.log1p(v) / np.log1p(h.max())))] for v in h)
    gaps = np.array([bins[i] for i in range(len(h)) if h[i] == 0])
    print("z %.2f-%.2f n=%4d |%s| 空档 %s" % (
        z0, z0 + 0.01, len(S), hh,
        "无" if len(gaps) == 0 else "%.3f-%.3f" % (gaps.min(), gaps.max())))

# 嘴区里的连通壳层：若有独立的下颌壳，会单独列出来
tri = r.I.reshape(-1, 3)
e = np.unique(np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1), axis=0)
par = np.arange(len(P))


def find(x):
    while par[x] != x:
        par[x] = par[par[x]]
        x = par[x]
    return x


for a, b in e:
    ra, rb = find(a), find(b)
    if ra != rb:
        par[ra] = rb
roots = np.array([find(i) for i in range(len(P))])
region = box(-0.14, 0.14, 0.24, 0.50, 0.15, 0.30)
uid, uc = np.unique(roots[region], return_counts=True)
rows = []
for u, c in zip(uid, uc):
    m = roots == u
    S = P[m]
    rows.append((int(c), S))
rows.sort(reverse=True, key=lambda t: t[0])
print("\n== 头部区 (z>0.15, |x|<0.14, y 0.24-0.50) 壳层 top 14 ==")
for c, S in rows[:14]:
    print("  n=%5d  x[%6.3f,%6.3f] y[%6.3f,%6.3f] z[%6.3f,%6.3f]  y均值 %.3f" % (
        c, S[:, 0].min(), S[:, 0].max(), S[:, 1].min(), S[:, 1].max(),
        S[:, 2].min(), S[:, 2].max(), S[:, 1].mean()))
print("该区共 %d 个壳层" % len(rows))
