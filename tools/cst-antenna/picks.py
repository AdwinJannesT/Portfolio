"""Read CST's pick cache (Model.bwc, ACIS SAT text): for every history step that picked a
vertex, edge or face, return the picked entity's real geometry.
key: (blockNumber, pickNumber) -> dict(solid, id, kind, point | (plane origin, normal, polygon))"""
import re
import numpy as np


def load(path):
    t = open(path, 'r', errors='replace').read()
    body = t.split('\n', 4)[4]
    ents = [e.strip().replace('\n', ' ') for e in body.split('#')]
    refs = lambda e: [int(x) for x in re.findall(r'\$(-?\d+)', e)]
    kind = lambda e: re.match(r'(?:-\d+\s+)?([\w\-]+)', e).group(1) if re.match(r'(?:-\d+\s+)?([\w\-]+)', e) else ''

    def point(i):
        nums = re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', ents[i].split('$-1 -1 -1 $-1', 1)[-1])
        return np.array([float(v) for v in nums[-3:]])

    def vertex_point(i):
        return point(refs(ents[i])[-1])

    # attribute chains: owner -> {label: value}
    attrs = {}
    for i, e in enumerate(ents):
        if 'attrib' not in kind(e):
            continue
        r = refs(e)
        owner = r[3] if len(r) > 3 else -1
        m = re.search(r'@\d+ (\S+)(?:\s+(\S+))?', e)
        if not m:
            continue
        label, val = m.group(1), m.group(2)
        if label.startswith('ncomponent1'):
            label, val = 'solid', label[1:]
        attrs.setdefault(owner, {})[label] = val

    def face_geom(i):
        e = ents[i]; r = refs(e)
        loop, surf = r[3], r[6]
        sense = 'reversed' in e
        se = ents[surf]
        nums = [float(v) for v in re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', se.split('$-1 -1 -1 $-1', 1)[-1])]
        origin, normal, udir = np.array(nums[0:3]), np.array(nums[3:6]), np.array(nums[6:9])
        if sense:
            normal = -normal
        # walk the outer loop: loop -> first coedge -> next coedges; coedge -> edge -> vertices
        pts = []
        lr = refs(ents[loop]); first = lr[3]; ce = first; guard = 0
        while guard < 500:
            cr = refs(ents[ce])
            nxt, edge = cr[2], cr[5]
            er = refs(ents[edge])
            v0, v1 = er[2], er[3]
            rev = 'reversed' in ents[ce]
            pts.append(vertex_point(v1 if rev else v0))
            ce = nxt; guard += 1
            if ce == first:
                break
        return origin, normal, udir, np.array(pts)

    picks = {}
    for owner, a in attrs.items():
        if 'backwd_blockNumber' not in a or owner < 0:
            continue
        k = kind(ents[owner])
        rec = {'solid': a.get('solid'), 'id': int(a['backwd_id']), 'kind': k}
        if k == 'vertex':
            rec['point'] = vertex_point(owner)
        elif k == 'face':
            rec['plane'] = face_geom(owner)
        elif k == 'edge':
            er = refs(ents[owner]); rec["ends"] = (vertex_point(er[2]), vertex_point(er[3]))
        picks[(int(a['backwd_blockNumber']), int(a['backwd_pickNumber']))] = rec
    return picks


if __name__ == '__main__':
    P = load('extracted/Model/3D/Model.bwc')
    for k in sorted(P):
        r = P[k]
        g = r.get('point')
        if g is None and 'plane' in r:
            o, n, u, pts = r['plane']; g = f'face n={n.round(3)} centre={((pts.min(0)+pts.max(0))/2).round(4)} verts={len(pts)}'
        elif g is None and 'ends' in r:
            g = f'edge {r["ends"][0].round(4)} -> {r["ends"][1].round(4)}'
        else:
            g = g.round(4)
        print(k, r['solid'], r['id'], r['kind'], g)
