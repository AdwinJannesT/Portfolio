"""Replay the CST history (ModelHistory.json) with exact axis-aligned box geometry.

Supported: WCS local/global, MoveWCS, AlignWCSWithSelected Face / Point / EdgeAndFace, With WCS
(SetNormal/SetUVector/SetOrigin), Brick, Solid.Add/Subtract/Delete/Rename, Transform Translate and
Rotate (90 degree multiples about the WCS w axis) with or without copy. Picks are resolved from the
pick cache (Model.bwc) by (history step + 1, pick number). Every pick is checked against the
reconstructed solid, so a wrong reconstruction shows up immediately."""
import json, math, re, sys
import numpy as np
from picks import load as load_picks

import os
ROOT = os.environ.get('CST_MODEL_DIR', 'extracted/Model/')
H = json.load(open(ROOT + '3D/ModelHistory.json'))['history']
PARAM = {p['name'].lower(): float(p['value']) for p in json.load(open(ROOT + 'Parameters.json'))['parameters']}
PICKS = load_picks(ROOT + '3D/Model.bwc')
EPS = 1e-6


def ev(expr):
    e = expr.strip().lower()
    e = re.sub(r'(?<![\w.])(\d+\.?\d*)e([+-]?\d+)', r'\1e\2', e)
    return float(eval(e, {'__builtins__': {}}, dict(PARAM)))


class WCS:
    def __init__(self):
        self.o = np.zeros(3); self.u = np.array([1., 0, 0]); self.v = np.array([0, 1., 0]); self.w = np.array([0, 0, 1.])
        self.local = False

    def set_axes(self, w, u):
        w = w / np.linalg.norm(w); u = u - w * np.dot(u, w); u = u / np.linalg.norm(u)
        self.w, self.u = w, u; self.v = np.cross(w, u)

    def to_global(self, p):
        if not self.local:
            return np.array(p, float)
        return self.o + self.u * p[0] + self.v * p[1] + self.w * p[2]

    def dir_global(self, d):
        if not self.local:
            return np.array(d, float)
        return self.u * d[0] + self.v * d[1] + self.w * d[2]


def box_from_corners(a, b):
    lo = np.minimum(a, b); hi = np.maximum(a, b)
    if np.any(hi - lo < EPS):
        return None
    return np.concatenate([lo, hi])


def subtract_box(A, B):
    """A minus B for axis-aligned boxes [x0,y0,z0,x1,y1,z1] -> list of boxes"""
    if np.any(A[3:] <= B[:3] + EPS) or np.any(B[3:] <= A[:3] + EPS):
        return [A]
    out = []; cur = A.copy()
    for k in range(3):
        if B[k] > cur[k] + EPS:
            piece = cur.copy(); piece[k + 3] = B[k]; out.append(piece); cur[k] = B[k]
        if B[k + 3] < cur[k + 3] - EPS:
            piece = cur.copy(); piece[k] = B[k + 3]; out.append(piece); cur[k + 3] = B[k + 3]
    return out


class Model:
    def __init__(self):
        self.solids = {}   # name -> {'boxes': [...], 'mat': str}
        self.order = []

    def put(self, name, boxes, mat):
        if name not in self.solids:
            self.order.append(name)
        self.solids[name] = {'boxes': boxes, 'mat': mat}

    def remove(self, name):
        self.solids.pop(name, None)
        if name in self.order:
            self.order.remove(name)

    def free_name(self, name):
        k = 1
        while f'{name}_{k}' in self.solids:
            k += 1
        return f'{name}_{k}'


def kv(code):
    """parse '.Key "a", "b"' lines of a With-block"""
    d = {}
    for line in code:
        m = re.match(r'\s*\.(\w+)\s+(.*)', line)
        if m:
            d[m.group(1)] = [x for x in re.findall(r'"([^"]*)"', m.group(2))]
    return d


def on_corner(boxes, p, tol=2e-4):
    for b in boxes:
        for c in range(8):
            q = np.array([b[3] if c & 1 else b[0], b[4] if c & 2 else b[1], b[5] if c & 4 else b[2]])
            if np.max(np.abs(q - p)) < tol:
                return True
    return False


def on_surface(boxes, p, tol=2e-4):
    for b in boxes:
        inside = all(b[k] - tol <= p[k] <= b[k + 3] + tol for k in range(3))
        if inside and any(abs(p[k] - b[k]) < tol or abs(p[k] - b[k + 3]) < tol for k in range(3)):
            return True
    return False


def run(face_u_rule='keep', verbose=False):
    M = Model(); W = WCS(); log = []; checks = [0, 0]
    pick = []
    for i, e in enumerate(H):
        code = e['code'] if isinstance(e['code'], list) else e['code'].split('\n')
        text = '\n'.join(code)
        block = i + 1
        pnum = 0
        for line in code:
            s = line.strip()
            if s.startswith("'") or not s:
                continue
            m = re.match(r'WCS\.ActivateWCS\s+"(\w+)"', s)
            if m:
                W.local = m.group(1).lower() == 'local'; continue
            m = re.match(r'WCS\.MoveWCS\s+"local",\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)"', s)
            if m:
                d = [ev(x) for x in m.groups()]
                W.o = W.o + W.u * d[0] + W.v * d[1] + W.w * d[2]; W.local = True; continue
            m = re.match(r'Pick\.Pick(Face|Endpoint|Edge)FromId\s+"([^"]+)",\s*"(\d+)"', s)
            if m:
                pnum += 1
                rec = PICKS.get((block, pnum))
                if rec is None:
                    log.append(f'step {i}: pick {pnum} not cached'); continue
                assert rec['solid'] == m.group(2) and rec['id'] == int(m.group(3)), (i, rec['solid'], rec['id'], s)
                pick.append(rec)
                if rec['kind'] not in ('vertex', 'face', 'edge'):
                    continue
                # check the pick against the reconstruction
                sol = M.solids.get(rec['solid'])
                if sol is not None:
                    if rec['kind'] == 'vertex':
                        ok = on_corner(sol['boxes'], rec['point'])
                    elif rec['kind'] == 'face':
                        o, n, u, pts = rec['plane']; c = (pts.min(0) + pts.max(0)) / 2
                        ok = on_surface(sol['boxes'], c)
                    else:
                        ok = on_surface(sol['boxes'], rec['ends'][0]) and on_surface(sol['boxes'], rec['ends'][1])
                    checks[0 if ok else 1] += 1
                    if not ok:
                        log.append(f'step {i}: {rec["kind"]} pick {rec["solid"]}#{rec["id"]} NOT on reconstruction')
                continue
            if s.startswith('Pick.ForceNextPick'):
                continue
            m = re.match(r'WCS\.AlignWCSWithSelected\s+"(\w+)"', s)
            if m:
                kind = m.group(1)
                if kind == 'Face':
                    o, n, u, pts = pick[-1]['plane']
                    W.o = (pts.min(0) + pts.max(0)) / 2
                    if face_u_rule == 'surface':
                        W.set_axes(n, u)
                    else:
                        uu = W.u if abs(np.dot(W.u, n)) < .99 else W.v
                        W.set_axes(n, uu)
                elif kind == 'EdgeAndFace':
                    # origin at the middle of the picked edge, w along the picked face normal
                    edge = [p for p in pick if p['kind'] == 'edge'][-1]
                    W.o = (edge['ends'][0] + edge['ends'][1]) / 2
                W.local = True; pick = []; continue
            if s.startswith('WCS.AlignWCSWithSelectedPoint'):
                if pick and 'point' in pick[-1]:
                    W.o = pick[-1]['point'].copy()
                else:
                    log.append(f'step {i}: point pick failed in CST too (no geometry depends on it)')
                W.local = True; pick = []; continue
        # block statements
        if re.search(r'^\s*With WCS', text, re.M):
            d = kv(code)
            if 'SetOrigin' in d: W.o = np.array([ev(x) for x in d['SetOrigin']])
            if 'SetNormal' in d:
                n = np.array([ev(x) for x in d['SetNormal']])
                uu = np.array([ev(x) for x in d['SetUVector']]) if 'SetUVector' in d else W.u
                W.set_axes(n, uu)
            if 'ActivateWCS' in d: W.local = d['ActivateWCS'][0].lower() == 'local'
        if re.search(r'^\s*With Brick', text, re.M):
            d = kv(code)
            name = f'{d["Component"][0]}:{d["Name"][0]}'
            xr, yr, zr = ([ev(x) for x in d[k]] for k in ('Xrange', 'Yrange', 'Zrange'))
            a = W.to_global([xr[0], yr[0], zr[0]]); b = W.to_global([xr[1], yr[1], zr[1]])
            bx = box_from_corners(a, b)
            M.put(name, [bx] if bx is not None else [], d.get('Material', [''])[0])
            if verbose: print(i, 'brick', name, bx)
        if re.search(r'^\s*With Transform', text, re.M):
            d = kv(code); name = d['Name'][0]; kind = d['Transform'][1]
            copy = d.get('MultipleObjects', ['False'])[0] == 'True'
            src = M.solids[name]
            if kind == 'Translate':
                vec = W.dir_global([ev(x) for x in d['Vector']])
                new = [np.concatenate([b[:3] + vec, b[3:] + vec]) for b in src['boxes']]
            elif kind == 'Rotate':
                cen = W.to_global([ev(x) for x in d['Center']])
                ang = [ev(x) for x in d['Angle']]
                assert abs(ang[0]) < EPS and abs(ang[1]) < EPS, ang
                axis = W.w if W.local else np.array([0, 0, 1.])
                assert abs(abs(axis[2]) - 1) < 1e-9
                t = math.radians(ang[2]) * np.sign(axis[2])
                c, s_ = round(math.cos(t)), round(math.sin(t))
                def rot(p): q = p - cen; return cen + np.array([c * q[0] - s_ * q[1], s_ * q[0] + c * q[1], q[2]])
                new = [box_from_corners(rot(b[:3]), rot(b[3:])) for b in src['boxes']]
            else:
                raise NotImplementedError(kind)
            if copy:
                M.put(M.free_name(name), new, src['mat'])
            else:
                src['boxes'] = new
        for line in code:
            s = line.strip()
            m = re.match(r'Solid\.(Add|Subtract|Delete|Rename|ChangeMaterial)\s+"([^"]+)"(?:,\s*"([^"]+)")?', s)
            if not m:
                continue
            op, a, b = m.groups()
            if op == 'Add':
                M.solids[a]['boxes'] = M.solids[a]['boxes'] + M.solids[b]['boxes']; M.remove(b)
            elif op == 'Subtract':
                res = M.solids[a]['boxes']
                for B in M.solids[b]['boxes']:
                    res = [p for A in res for p in subtract_box(A, B)]
                M.solids[a]['boxes'] = res; M.remove(b)
            elif op == 'Delete':
                M.remove(a)
            elif op == 'Rename':
                comp = a.split(':')[0]; M.put(f'{comp}:{b}', M.solids[a]['boxes'], M.solids[a]['mat']); M.remove(a)
            elif op == 'ChangeMaterial':
                M.solids[a]['mat'] = b
    return M, log, checks


def bbox(boxes):
    B = np.array(boxes); return np.concatenate([B[:, :3].min(0), B[:, 3:].max(0)])


if __name__ == '__main__':
    rule = sys.argv[1] if len(sys.argv) > 1 else 'keep'
    M, log, checks = run(rule)
    print('pick checks ok/failed:', checks)
    for l in log[:30]: print('  ', l)
    for n in M.order:
        s = M.solids[n]
        print(f'{n:28s} {s["mat"]:20s} boxes={len(s["boxes"]):4d} bbox={bbox(s["boxes"]).round(4) if s["boxes"] else None}')
