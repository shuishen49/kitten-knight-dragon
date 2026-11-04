#!/usr/bin/env python3
"""最差拉伸边剖析：区分“真的被撕开”与“极短边把比例放大”。
每条边给出静止长 / 变形后长 / 绝对变化 |delta|，以及两端顶点的主导骨与权重。
用法: python tools/edgeworst.py --clip flap --time 0 --minlen 0"""
import sys, argparse
import numpy as np
sys.path.insert(0, "tools")
import rigview as rv
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ap = argparse.ArgumentParser()
ap.add_argument("--clip", default="flap")
ap.add_argument("--time", type=float, default=0.0)
ap.add_argument("--minlen", type=float, default=0.0)
ap.add_argument("--top", type=int, default=8)
A = ap.parse_args()
r = rv.Rig()
nb = len(r.bone_names)
WF = np.zeros((len(r.P), nb))
ar = np.arange(len(r.P))
for c in range(r.J.shape[1]):
    np.add.at(WF, (ar, np.clip(r.J[:, c], 0, nb - 1)), r.W[:, c])
tri = r.I.reshape(-1, 3)
e = np.unique(np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1), axis=0)
rl = np.linalg.norm(r.P[e[:, 0]] - r.P[e[:, 1]], axis=1)
keep = rl > A.minlen
e, rl = e[keep], rl[keep]
p, _, _ = r.skin(A.clip, A.time)
dl = np.linalg.norm(p[e[:, 0]] - p[e[:, 1]], axis=1)
rat, dd = dl / rl, np.abs(dl - rl)
print("clip %s t=%.2f  边 %d 条 (静止长 > %.4f)" % (A.clip, A.time, len(rl), A.minlen))
print("  |delta| 均值 %.5f  p99 %.5f  最大 %.5f   >0.01 的边 %d 条" % (
    dd.mean(), np.percentile(dd, 99), dd.max(), int((dd > 0.01).sum())))


def wstr(v):
    return " ".join("%s %.2f" % (r.bone_names[k], WF[v, k]) for k in np.argsort(-WF[v])[:3] if WF[v, k] > 0.05)


for label, order in (("按比例最差", np.argsort(-rat)), ("按绝对变化最差", np.argsort(-dd))):
    print("== %s top %d ==" % (label, A.top))
    for i in order[:A.top]:
        a, b = e[i]
        print("  rat %6.2fx  len %.5f -> %.5f  |d| %.5f" % (rat[i], rl[i], dl[i], dd[i]))
        print("     %s A %s" % (np.round(r.P[a], 3), wstr(a)))
        print("     %s B %s" % (np.round(r.P[b], 3), wstr(b)))
