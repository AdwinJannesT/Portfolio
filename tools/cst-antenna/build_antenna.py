"""Rebuilt CST antenna -> watertight meshes -> GLB (+ a base64 .js copy that loads from file://).

Each solid is the exact union of its boxes. The surface is extracted on the compressed grid of all
box coordinates, so there are no internal faces, and coplanar faces are merged into rectangles."""
import json, struct, base64, sys
import numpy as np
from replay import run

OUT_GLB = sys.argv[1] if len(sys.argv) > 1 else 'cst-antenna.glb'
OUT_JS = sys.argv[2] if len(sys.argv) > 2 else 'cst-antenna.js'

M, log, checks = run('keep')
assert checks[1] <= 1, checks

LABEL = {'component1:substrate': 'substrate', 'component1:ground': 'ground plane',
         'component1:Feed': 'feed network 1', 'component1:Feed_1': 'feed network 2',
         'component1:Feed_2': 'feed network 3', 'component1:Feed_3': 'feed network 4',
         'component1:square para': 'parasitic patch'}


def greedy_rects(mask):
    """split a boolean 2D mask into rectangles (i0, i1, j0, j1) exclusive"""
    m = mask.copy(); out = []
    H, W = m.shape
    for i in range(H):
        j = 0
        while j < W:
            if not m[i, j]:
                j += 1; continue
            j1 = j
            while j1 < W and m[i, j1]: j1 += 1
            i1 = i + 1
            while i1 < H and m[i1, j:j1].all(): i1 += 1
            m[i:i1, j:j1] = False
            out.append((i, i1, j, j1)); j = j1
    return out


def surface(boxes):
    B = np.array(boxes)
    xs = np.unique(np.round(np.concatenate([B[:, 0], B[:, 3]]), 7))
    ys = np.unique(np.round(np.concatenate([B[:, 1], B[:, 4]]), 7))
    zs = np.unique(np.round(np.concatenate([B[:, 2], B[:, 5]]), 7))
    occ = np.zeros((len(xs) - 1, len(ys) - 1, len(zs) - 1), bool)
    for b in B:
        i0, i1 = np.searchsorted(xs, round(b[0], 7)), np.searchsorted(xs, round(b[3], 7))
        j0, j1 = np.searchsorted(ys, round(b[1], 7)), np.searchsorted(ys, round(b[4], 7))
        k0, k1 = np.searchsorted(zs, round(b[2], 7)), np.searchsorted(zs, round(b[5], 7))
        occ[i0:i1, j0:j1, k0:k1] = True
    P = np.pad(occ, 1)
    pos, nrm, idx = [], [], []
    coords = (xs, ys, zs)

    def quad(axis, plane_val, a_rng, b_rng, sign):
        # axis: normal axis; a, b: the other two axes in cyclic order
        a, b = (axis + 1) % 3, (axis + 2) % 3
        n = np.zeros(3); n[axis] = sign
        corners = []
        for (u, v) in ((a_rng[0], b_rng[0]), (a_rng[1], b_rng[0]), (a_rng[1], b_rng[1]), (a_rng[0], b_rng[1])):
            p = np.zeros(3); p[axis] = plane_val; p[a] = u; p[b] = v; corners.append(p)
        base = len(pos)
        pos.extend(corners); nrm.extend([n] * 4)
        if sign > 0: idx.extend([base, base + 1, base + 2, base, base + 2, base + 3])
        else: idx.extend([base, base + 2, base + 1, base, base + 3, base + 2])

    for axis in range(3):
        a, b = (axis + 1) % 3, (axis + 2) % 3
        n_ax = occ.shape[axis]
        for k in range(n_ax + 1):
            sl_lo = np.take(P, k, axis=axis)       # cell before the plane (padded index k)
            sl_hi = np.take(P, k + 1, axis=axis)   # cell after the plane
            # move the remaining two axes into (a, b) order
            rem = [ax for ax in range(3) if ax != axis]
            def ab(arr):
                arr = arr[1:-1, 1:-1]
                return arr if rem == [a, b] else arr.T
            lo, hi = ab(sl_lo), ab(sl_hi)
            for mask, sign in ((lo & ~hi, 1), (hi & ~lo, -1)):
                if not mask.any(): continue
                for (i0, i1, j0, j1) in greedy_rects(mask):
                    quad(axis, coords[axis][k], (coords[a][i0], coords[a][i1]), (coords[b][j0], coords[b][j1]), sign)
    return np.array(pos, np.float32), np.array(nrm, np.float32), np.array(idx, np.uint32)


# centre on the board, keep millimetres; glTF is Y-up: (x, y, z)_cst -> (x, z, -y)
sub = np.array(M.solids['component1:substrate']['boxes'])
cx = (sub[:, 0].min() + sub[:, 3].max()) / 2; cy = (sub[:, 1].min() + sub[:, 4].max()) / 2

bin_parts = []; off = 0; views = []; accs = []; meshes = []; nodes = []


def add(arr, target, typ, comp, mm=False):
    global off
    b = arr.tobytes()
    while off % 4: bin_parts.append(b'\0'); off += 1
    views.append({'buffer': 0, 'byteOffset': off, 'byteLength': len(b), 'target': target}); bin_parts.append(b); off += len(b)
    a = {'bufferView': len(views) - 1, 'componentType': comp, 'count': int(arr.shape[0]), 'type': typ}
    if mm: a['min'] = arr.min(0).tolist(); a['max'] = arr.max(0).tolist()
    accs.append(a); return len(accs) - 1


materials = [
    {'name': 'FR-4 (lossy)', 'pbrMetallicRoughness': {'baseColorFactor': [0.085, 0.10, 0.055, 1], 'metallicFactor': 0, 'roughnessFactor': 0.7}},
    {'name': 'Copper (annealed)', 'pbrMetallicRoughness': {'baseColorFactor': [0.86, 0.34, 0.14, 1], 'metallicFactor': 1, 'roughnessFactor': 0.35}},
]
stats = []
for name in M.order:
    s = M.solids[name]
    if not s['boxes']: continue
    p, n, i = surface(s['boxes'])
    p = p.copy(); p[:, 0] -= cx; p[:, 1] -= cy
    P = np.stack([p[:, 0], p[:, 2], -p[:, 1]], 1).astype(np.float32)
    N = np.stack([n[:, 0], n[:, 2], -n[:, 1]], 1).astype(np.float32)
    ia = add(i, 34963, 'SCALAR', 5125); pa = add(P, 34962, 'VEC3', 5126, True); na = add(N, 34962, 'VEC3', 5126)
    mat = 0 if s['mat'].startswith('FR-4') else 1
    meshes.append({'name': LABEL[name], 'primitives': [{'attributes': {'POSITION': pa, 'NORMAL': na}, 'indices': ia, 'material': mat}]})
    nodes.append({'name': LABEL[name], 'mesh': len(meshes) - 1, 'extras': {'cstSolid': name, 'material': s['mat']}})
    stats.append((LABEL[name], len(i) // 3))

root = {'name': 'MIMO antenna (from CST project)', 'children': list(range(len(nodes))),
        'extras': {'units': 'mm', 'source': 'FYP 3rd stage with para.cst, ModelHistory.json replayed; picks resolved from Model.bwc'}}
nodes.append(root)
binary = b''.join(bin_parts)
while len(binary) % 4: binary += b'\0'
gltf = {'asset': {'version': '2.0', 'generator': 'cst-history-replay'}, 'scene': 0, 'scenes': [{'nodes': [len(nodes) - 1]}],
        'nodes': nodes, 'meshes': meshes, 'materials': materials, 'accessors': accs, 'bufferViews': views,
        'buffers': [{'byteLength': len(binary)}]}
js = json.dumps(gltf, separators=(',', ':')).encode()
while len(js) % 4: js += b' '
glb = struct.pack('<III', 0x46546C67, 2, 28 + len(js) + len(binary)) + struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(binary), 0x004E4942) + binary
open(OUT_GLB, 'wb').write(glb)
open(OUT_JS, 'w').write('/* 3D model of the MIMO antenna, rebuilt from the CST Studio Suite project (binary glTF, base64, millimetres). */\n'
                        'window.CST_ANTENNA_GLB="' + base64.b64encode(glb).decode() + '";\n')
print('GLB', len(glb), 'bytes;', stats)
