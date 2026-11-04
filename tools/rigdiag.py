#!/usr/bin/env python3
"""跟随率诊断：部位实际位移 / 完全刚性跟随自家骨骼的位移。
比值远小于 1 说明权重被摊薄，该部位在动画里像橡皮泥 —— 绑骨坏掉的核心症状。"""
import sys
import numpy as np
sys.path.insert(0, "tools")
import rigview as rv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

r = rv.Rig()
jr = r.joint_rest()
nb = len(r.joint_nodes)
segl = []
for k, nn in enumerate(r.joint_nodes):
    kids = [c for c in r.g["nodes"][nn].get("children", []) if c in r.joint_nodes]
    b = jr[r.joint_nodes.index(kids[0])] if kids else jr[k]
    segl.append((jr[k], b, rv.RAD_GEO.get(r.bone_names[k], 0.08)))
d = np.empty((len(r.P), nb))
for k, (a, b, rad) in enumerate(segl):
    dd = b - a
    L2 = float(dd @ dd)
    if L2 < 1e-12:
        dist = np.linalg.norm(r.P - a, axis=1)
    else:
        u = np.clip(((r.P - a) @ dd) / L2, 0, 1)
        dist = np.linalg.norm(r.P - (a + u[:, None] * dd), axis=1)
    d[:, k] = dist / rad
near = np.argmin(d, 1)

# 展开成每骨骼权重表（文件里存的是 top4 的 JOINTS/WEIGHTS 对）
WF = np.zeros((len(r.P), nb))
ar = np.arange(len(r.P))
for c in range(r.J.shape[1]):
    np.add.at(WF, (ar, np.clip(r.J[:, c], 0, nb - 1)), r.W[:, c])
dom = np.argmax(WF, 1)
mass = WF.mean(0)
print("权重质量（每骨骼平均权重）: " + "  ".join(
    "%s %.3f" % (r.bone_names[k], mass[k]) for k in np.argsort(-mass)[:8]))
print("权重主导骨 == 几何最近骨 的比例 %.3f" % float((near == dom).mean()))
own_d = d[ar, dom]
for lvl in (2.0, 3.0, 5.0):
    m = own_d > lvl
    print("  主导骨距顶点超过 %g 倍骨半径: %6d 个 (%.1f%%)" % (lvl, int(m.sum()), 100.0 * m.mean()))

ph = np.concatenate([r.P, np.ones((len(r.P), 1))], 1)
CASES = [("bite", 0.30), ("claw", 0.40), ("flap", 0.45), ("breath", 1.20), ("sweep", 0.62), ("roar", 0.75)]
for clip, t in CASES:
    lt, lr = r.node_locals(clip, t)
    W = r.world(lt, lr)
    jm = np.stack([W[nn] @ r.IBM[k] for k, nn in enumerate(r.joint_nodes)])
    p, _, _ = r.skin(clip, t)
    act = np.linalg.norm(p - r.P, axis=1)
    print("== %s t=%.2f   全场位移 均值 %.4f 最大 %.4f ==" % (clip, t, act.mean(), act.max()))
    rows = []
    for k in range(nb):
        m = near == k
        c = int(m.sum())
        if c < 60:
            continue
        rp = np.einsum("ij,nj->ni", jm[k], ph[m])[:, :3]
        rig = float(np.linalg.norm(rp - r.P[m], axis=1).mean())
        wm = WF[m].mean(0)
        top = int(np.argmax(wm))
        rows.append((float(act[m].mean()), r.bone_names[k], c, float(WF[m, k].mean()),
                     r.bone_names[top], float(wm[top]), rig))
    rows.sort(reverse=True)
    for a, nm, c, own, top, tw, rig in rows[:10]:
        print("   %-7s n=%5d 实际位移 %.4f / 刚性 %.4f = %4.2f | 自家权重 %.2f | 实际主导 %-7s %.2f" % (
            nm, c, a, rig, a / max(rig, 1e-6), own, top, tw))
