#!/usr/bin/env python3
"""黑龙绑定/动画体检：解析 GLB -> CPU 线性混合蒙皮 -> ASCII 视图 + 拉伸/撕裂度量。
用法:
  python tools/rigview.py info
  python tools/rigview.py weights
  python tools/rigview.py metrics [clip ...]
  python tools/rigview.py view --clip bite --times 0,.3,.7 --view side --mode depth
"""
import struct, json, math, argparse
import numpy as np

CT = {5120: ("i1", 1), 5121: ("u1", 1), 5122: ("i2", 2), 5123: ("u2", 2), 5125: ("u4", 4), 5126: ("f4", 4)}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_D = _O = None
GLB = "models/dragon-anim.glb"


def parse_glb(path):
    d = open(path, "rb").read()
    jlen = struct.unpack("<I", d[12:16])[0]
    return json.loads(d[20:20 + jlen]), d, 20 + jlen + 8


def read_acc(g, d, off, ai):
    a = g["accessors"][ai]
    bv = g["bufferViews"][a["bufferView"]]
    dt, sz = CT[a["componentType"]]
    nc = NC[a["type"]]
    base = off + bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or sz * nc
    if stride == sz * nc:
        arr = np.frombuffer(d, dtype=dt, count=a["count"] * nc, offset=base).reshape(a["count"], nc)
        return arr.astype(np.float64)
    out = np.empty((a["count"], nc), dtype=np.float64)
    for i in range(a["count"]):
        out[i] = np.frombuffer(d, dtype=dt, count=nc, offset=base + i * stride)
    return out


def qmat(q):
    x, y, z, w = q
    n = x * x + y * y + z * z + w * w
    if n < 1e-12:
        return np.eye(3)
    s = 2.0 / n
    return np.array([
        [1 - s * (y * y + z * z), s * (x * y - w * z), s * (x * z + w * y)],
        [s * (x * y + w * z), 1 - s * (x * x + z * z), s * (y * z - w * x)],
        [s * (x * z - w * y), s * (y * z + w * x), 1 - s * (x * x + y * y)]])


def slerp(a, b, t):
    d = float(np.dot(a, b))
    if d < 0:
        b = -b
        d = -d
    if d > 0.9995:
        r = a + t * (b - a)
        return r / np.linalg.norm(r)
    th = math.acos(max(-1.0, min(1.0, d)))
    s = math.sin(th)
    return (math.sin((1 - t) * th) * a + math.sin(t * th) * b) / s


class Rig:
    def __init__(self, path=GLB):
        g, d, off = parse_glb(path)
        self.g = g
        self._d = d
        self._off = off
        prim = g["meshes"][0]["primitives"][0]
        self.P = read_acc(g, d, off, prim["attributes"]["POSITION"])
        self.N = read_acc(g, d, off, prim["attributes"]["NORMAL"])
        self.J = read_acc(g, d, off, prim["attributes"]["JOINTS_0"]).astype(int)
        self.W = read_acc(g, d, off, prim["attributes"]["WEIGHTS_0"])
        self.I = read_acc(g, d, off, prim["indices"]).astype(int).ravel()
        sk = g["skins"][0]
        self.joint_nodes = sk["joints"]
        self.bone_names = [g["nodes"][n].get("name") for n in self.joint_nodes]
        self.IBM = read_acc(g, d, off, sk["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
        self.parent = {}
        self.local_t = {}
        self.local_r = {}
        for i, nd in enumerate(g["nodes"]):
            self.local_t[i] = np.array(nd.get("translation", [0, 0, 0]), dtype=np.float64)
            self.local_r[i] = np.array(nd.get("rotation", [0, 0, 0, 1]), dtype=np.float64)
            for c in nd.get("children", []):
                self.parent[c] = i
        self.order = []
        stack = [i for i in range(len(g["nodes"])) if i not in self.parent]
        while stack:
            n = stack.pop()
            self.order.append(n)
            stack.extend(g["nodes"][n].get("children", []))
        self.clips = {a["name"]: self._clip(a) for a in g["animations"]}

    def _clip(self, a):
        tr = {}
        for ch in a["channels"]:
            s = a["samplers"][ch["sampler"]]
            tr.setdefault(ch["target"]["node"], {})[ch["target"]["path"]] = (
                read_acc(self.g, self._d, self._off, s["input"]).ravel(),
                read_acc(self.g, self._d, self._off, s["output"]))
        dur = max(float(t[-1]) for c in tr.values() for t, _ in c.values())
        return {"dur": dur, "tr": tr}

    def _track(self, times, vals, t):
        if t <= times[0]:
            return vals[0]
        if t >= times[-1]:
            return vals[-1]
        i = max(0, min(int(np.searchsorted(times, t)) - 1, len(times) - 2))
        a, b = times[i], times[i + 1]
        u = 0.0 if b <= a else (t - a) / (b - a)
        if vals.shape[1] == 4:
            return slerp(vals[i], vals[i + 1], u)
        return vals[i] + u * (vals[i + 1] - vals[i])

    def node_locals(self, clip=None, t=0.0):
        lt = {i: self.local_t[i].copy() for i in self.local_t}
        lr = {i: self.local_r[i].copy() for i in self.local_r}
        if clip is not None:
            for node, paths in self.clips[clip]["tr"].items():
                if "translation" in paths:
                    times, vals = paths["translation"]
                    lt[node] = self._track(times, vals, t)
                if "rotation" in paths:
                    times, vals = paths["rotation"]
                    lr[node] = self._track(times, vals, t)
        return lt, lr

    def world(self, lt, lr):
        out = {}
        for n in self.order:
            m = np.eye(4)
            m[:3, :3] = qmat(lr[n])
            m[:3, 3] = lt[n]
            p = self.parent.get(n)
            out[n] = m if p is None else out[p] @ m
        return out

    def skin(self, clip=None, t=0.0):
        lt, lr = self.node_locals(clip, t)
        W = self.world(lt, lr)
        jm = np.stack([W[n] @ self.IBM[k] for k, n in enumerate(self.joint_nodes)])
        jw = np.stack([W[n] for n in self.joint_nodes])
        ph = np.concatenate([self.P, np.ones((len(self.P), 1))], 1)
        nh = np.concatenate([self.N, np.zeros((len(self.N), 1))], 1)
        acc = np.zeros((len(self.P), 4))
        accn = np.zeros((len(self.N), 4))
        for k in range(4):
            M = jm[self.J[:, k]]
            w = self.W[:, k][:, None]
            acc += w * np.einsum("nij,nj->ni", M, ph)
            accn += w * np.einsum("nij,nj->ni", M, nh)
        nv = accn[:, :3]
        ln = np.linalg.norm(nv, axis=1, keepdims=True)
        ln[ln < 1e-9] = 1
        return acc[:, :3], nv / ln, jw

    def joint_rest(self):
        W = self.world({i: self.local_t[i] for i in self.local_t}, {i: self.local_r[i] for i in self.local_r})
        return np.array([W[n][:3, 3] for n in self.joint_nodes])


def cmd_info(r):
    print("verts %d  tris %d  joints %d" % (len(r.P), len(r.I) // 3, len(r.bone_names)))
    P = r.P
    print("rest bbox  x %.3f..%.3f  y %.3f..%.3f  z %.3f..%.3f" % (
        P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max(), P[:, 2].min(), P[:, 2].max()))
    for n, c in r.clips.items():
        bones = " ".join(sorted(r.g["nodes"][i].get("name") for i in c["tr"]))
        print("  %-7s dur %.3fs  keys %s" % (n, c["dur"], bones))
    p, _, _ = r.skin()
    print("rest-pose LBS max error vs authored verts: %.3e" % np.abs(p - r.P).max())
    tri = r.I.reshape(-1, 3)
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    el = np.linalg.norm(r.P[e[:, 0]] - r.P[e[:, 1]], axis=1)
    print("edge length: median %.5f  p10 %.5f  p90 %.5f" % (np.median(el), np.percentile(el, 10), np.percentile(el, 90)))


def cmd_weights(r):
    dom = np.argmax(r.W, 1)
    wsum = r.W.sum(1)
    print("weight-row sums: min %.3f  mean %.3f  max %.3f" % (wsum.min(), wsum.mean(), wsum.max()))
    print("argmax histogram: %s" % dict(zip(r.bone_names, np.bincount(dom, minlength=len(r.bone_names)).tolist())))
    print("root weight: mean %.3f  verts with root>0.25: %d" % (r.W[:, 0].mean(), int((r.W[:, 0] > 0.25).sum())))
    jr = r.joint_rest()
    print("%-8s %6s  %-42s %s" % ("bone", "verts", "owned-vert bbox (x,y,z)", "dist-to-bone max/mean"))
    for k, name in enumerate(r.bone_names):
        m = dom == k
        cnt = int(m.sum())
        if cnt == 0:
            print("%-8s %6d  (none)" % (name, cnt))
            continue
        Pt = r.P[m]
        kids = [c for c in r.g["nodes"][r.joint_nodes[k]].get("children", []) if c in r.joint_nodes]
        a = jr[k]
        b = jr[r.joint_nodes.index(kids[0])] if kids else a
        d = b - a
        L2 = float(d @ d)
        if L2 < 1e-12:
            dist = np.linalg.norm(Pt - a, axis=1)
        else:
            u = np.clip(((Pt - a) @ d) / L2, 0, 1)
            dist = np.linalg.norm(Pt - (a + u[:, None] * d), axis=1)
        print("%-8s %6d  x[%6.3f,%6.3f] y[%6.3f,%6.3f] z[%6.3f,%6.3f]  %.3f / %.3f" % (
            name, cnt, Pt[:, 0].min(), Pt[:, 0].max(), Pt[:, 1].min(), Pt[:, 1].max(),
            Pt[:, 2].min(), Pt[:, 2].max(), dist.max(), dist.mean()))


def cmd_metrics(r, names, nsample=13):
    tri = r.I.reshape(-1, 3)
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    e = np.unique(np.sort(e, axis=1), axis=0)
    ia, ib = e[:, 0], e[:, 1]
    rl = np.linalg.norm(r.P[ia] - r.P[ib], axis=1)
    keep = rl > 0.002
    ia, ib, rl = ia[keep], ib[keep], rl[keep]
    print("checked edges:", len(rl))
    for name in names:
        c = r.clips[name]
        allr = []
        worst = (0.0, 0.0, None)
        for i in range(nsample):
            t = c["dur"] * i / (nsample - 1)
            p, _, _ = r.skin(name, t)
            rat = np.linalg.norm(p[ia] - p[ib], axis=1) / rl
            allr.append(rat)
            j = int(np.argmax(rat))
            if rat[j] > worst[1]:
                worst = (t, float(rat[j]), np.round((r.P[ia[j]] + r.P[ib[j]]) / 2, 3))
        allr = np.concatenate(allr)
        print("%-7s max %5.2fx  p99.9 %5.2fx  edges>1.6x %5d  >2.5x %4d  worst t=%.2f @ %s" % (
            name, worst[1], np.percentile(allr, 99.9), int((allr > 1.6).sum()), int((allr > 2.5).sum()),
            worst[0], worst[2]))

    # 壳层撕裂检查：同一连通壳层被相距很远的骨头分别主导 => 播动画时会被撕开
    nv = len(r.P)
    par = np.arange(nv)

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    for u, v in e:
        ru, rv = find(u), find(v)
        if ru != rv:
            par[ru] = rv
    roots = np.array([find(i) for i in range(nv)])
    dom = np.argmax(r.W, 1)
    jr = r.joint_rest()
    bad = []
    for u in np.unique(roots):
        m = roots == u
        if m.sum() < 40:
            continue
        bs = np.unique(dom[m])
        if len(bs) < 2:
            continue
        d = np.linalg.norm(jr[bs][:, None, :] - jr[bs][None, :, :], axis=2)
        if d.max() > 0.18:
            bad.append((int(m.sum()), round(float(d.max()), 3), [r.bone_names[i] for i in bs]))
    bad.sort(reverse=True)
    print("shells (>=40 verts) split across far-apart bones: %d" % len(bad))
    for c, dd, bn in bad[:8]:
        print("   %5d verts  bone-span %.3f  bones=%s" % (c, dd, " ".join(bn)))


LETTER = {"root": "R", "spine": "S", "chest": "C", "neck1": "n", "neck2": "N", "head": "H",
          "tail0": "0", "tail1": "1", "tail2": "2", "tail3": "3"}
# 几何最近骨骼用：各部位的合理粗细（骨间距量级）
RAD_GEO = {"root": 0.11, "spine": 0.10, "chest": 0.11, "neck1": 0.075, "neck2": 0.07, "head": 0.085,
           "wingL0": 0.09, "wingL1": 0.09, "wingL2": 0.09, "wingR0": 0.09, "wingR1": 0.09, "wingR2": 0.09,
           "legFL0": 0.07, "legFL1": 0.06, "legFR0": 0.07, "legFR1": 0.06,
           "legHL0": 0.07, "legHL1": 0.06, "legHR0": 0.07, "legHR1": 0.06,
           "tail0": 0.07, "tail1": 0.065, "tail2": 0.06, "tail3": 0.065}


def bone_letter(nm):
    if nm in LETTER:
        return LETTER[nm]
    if nm.startswith("wing"):
        return "W" if nm[4] == "L" else "w"
    if nm.startswith("leg"):
        return ("F" if nm[3] == "F" else "B") + nm[-1]
    return "?"


def cmd_bones(r, clip, times):
    for t in times:
        lt, lr = r.node_locals(clip, t)
        W = r.world(lt, lr)
        print("== bones %s t=%.2f ==" % (clip, t))
        for k, n in enumerate(r.joint_nodes):
            print("  %-7s %s" % (r.bone_names[k], np.round(W[n][:3, 3], 3)))


def cmd_view(r, clip, times, view, mode, rows):
    if view == "side":
        f = lambda p: (p[:, 2], p[:, 1], p[:, 0])
    elif view == "front":
        f = lambda p: (-p[:, 0], p[:, 1], p[:, 2])
    elif view == "back":
        f = lambda p: (-p[:, 0], p[:, 1], -p[:, 2])
    elif view == "top":
        f = lambda p: (p[:, 2], p[:, 0], p[:, 1])
    else:
        c, s = math.cos(0.9), math.sin(0.9)
        f = lambda p: (p[:, 2] * c - p[:, 0] * s, p[:, 1], p[:, 2] * s + p[:, 0] * c)
    L = np.array([0.45, 0.8, 0.45])
    L /= np.linalg.norm(L)
    ramp = " .:-=+*#%@"
    tri = r.I.reshape(-1, 3)
    dom = np.argmax(r.W, 1)
    # 几何最近骨骼（与权重无关）：作为“这块应该归谁”的基准
    jr = r.joint_rest()
    segl = []
    for k, n in enumerate(r.joint_nodes):
        kids = [c for c in r.g["nodes"][n].get("children", []) if c in r.joint_nodes]
        b = jr[r.joint_nodes.index(kids[0])] if kids else jr[k]
        segl.append((jr[k], b, RAD_GEO.get(r.bone_names[k], 0.08)))
    dgeo = np.empty((len(r.P), len(segl)))
    for k, (aa, bb, rad) in enumerate(segl):
        dd = bb - aa
        L2 = float(dd @ dd)
        if L2 < 1e-12:
            dist = np.linalg.norm(r.P - aa, axis=1)
        else:
            u = np.clip(((r.P - aa) @ dd) / L2, 0, 1)
            dist = np.linalg.norm(r.P - (aa + u[:, None] * dd), axis=1)
        dgeo[:, k] = dist / rad
    near = np.argmin(dgeo, 1)
    for t in times:
        p, n, _ = r.skin(clip, t)
        sx, sy, dep = f(p)
        nx, ny, ndv = f(n)
        cols = max(50, min(170, int(rows * (sx.max() - sx.min()) / (2.15 * max(1e-6, sy.max() - sy.min())))))
        x0, x1, y0, y1 = sx.min(), sx.max(), sy.min(), sy.max()
        pad = 0.03 * max(x1 - x0, y1 - y0)
        x0 -= pad; x1 += pad; y0 -= pad; y1 += pad
        gx = np.clip(((sx - x0) / (x1 - x0) * (cols - 1)).round().astype(int), 0, cols - 1)
        gy = np.clip(((y1 - sy) / (y1 - y0) * (rows - 1)).round().astype(int), 0, rows - 1)
        grid = [[" "] * cols for _ in range(rows)]
        zgrid = np.full((rows, cols), -1e9)
        for ti in np.argsort(dep[tri].mean(1)):
            v = tri[ti]
            X, Y = gx[v], gy[v]
            xa, xb, ya, yb = X.min(), X.max(), Y.min(), Y.max()
            if xb - xa > cols * 0.8 or yb - ya > rows * 0.95:
                continue
            gxx, gyy = np.meshgrid(np.arange(xa, xb + 1), np.arange(ya, yb + 1))
            det = (Y[1] - Y[2]) * (X[0] - X[2]) + (X[2] - X[1]) * (Y[0] - Y[2])
            if abs(det) < 1e-9:
                continue
            l1 = ((Y[1] - Y[2]) * (gxx - X[2]) + (X[2] - X[1]) * (gyy - Y[2])) / det
            l2 = ((Y[2] - Y[0]) * (gxx - X[2]) + (X[0] - X[2]) * (gyy - Y[2])) / det
            l3 = 1 - l1 - l2
            m = (l1 >= -0.03) & (l2 >= -0.03) & (l3 >= -0.03)
            if not m.any():
                continue
            ys, xs = gyy[m], gxx[m]
            if mode == "sil":
                zd = float(dep[v].mean())
                for yy, xx in zip(ys, xs):
                    if zd > zgrid[yy][xx]:
                        zgrid[yy][xx] = zd
                continue
            if mode == "part":
                ch = bone_letter(r.bone_names[near[v[0]]])
                for yy, xx in zip(ys, xs):
                    grid[yy][xx] = ch
            else:
                sh = float(np.dot(np.array([nx[v].mean(), ny[v].mean(), ndv[v].mean()]), L))
                if sh < 0:
                    sh = -sh * 0.45
                ch = ramp[int(np.clip(sh, 0, 1) * (len(ramp) - 1))]
                for yy, xx in zip(ys, xs):
                    grid[yy][xx] = ch
        if mode == "sil":
            for yy in range(rows):
                for xx in range(cols):
                    z = zgrid[yy][xx]
                    if z <= -1e8:
                        continue
                    nb = []
                    if yy > 0:
                        nb.append(zgrid[yy - 1, xx])
                    if yy < rows - 1:
                        nb.append(zgrid[yy + 1, xx])
                    if xx > 0:
                        nb.append(zgrid[yy, xx - 1])
                    if xx < cols - 1:
                        nb.append(zgrid[yy, xx + 1])
                    mz = max(nb) if nb else -1e9
                    grid[yy][xx] = "#" if (mz <= -1e8 or abs(z - mz) > 0.012) else "."
        print("== %s t=%.2f view=%s mode=%s ==" % (clip, t, view, mode))
        print("+" + "-" * cols + "+")
        for row in grid:
            print("|" + "".join(row) + "|")
        print("+" + "-" * cols + "+")


def main():
    global _D, _O
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("clips", nargs="*")
    ap.add_argument("--glb", default=GLB)
    ap.add_argument("--clip", default="idle")
    ap.add_argument("--times", default="0")
    ap.add_argument("--view", default="side")
    ap.add_argument("--mode", default="depth")
    ap.add_argument("--rows", type=int, default=40)
    a = ap.parse_args()
    _, _D, _O = parse_glb(a.glb)
    r = Rig(a.glb)
    if a.cmd == "info":
        cmd_info(r)
    elif a.cmd == "weights":
        cmd_weights(r)
    elif a.cmd == "metrics":
        cmd_metrics(r, a.clips or list(r.clips))
    elif a.cmd == "view":
        cmd_view(r, a.clip, [float(x) for x in a.times.split(",")], a.view, a.mode, a.rows)
    elif a.cmd == "bones":
        cmd_bones(r, a.clip, [float(x) for x in a.times.split(",")])
    else:
        print("unknown cmd", a.cmd)


if __name__ == "__main__":
    main()
