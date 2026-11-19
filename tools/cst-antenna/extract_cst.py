"""Unpack a CST Studio Suite .cst project (a ZIP archive with renamed signatures) without changing it.
usage: python extract_cst.py "FYP 3rd stage with para.cst" extracted"""
import os, struct, sys, zlib

src, out = sys.argv[1], sys.argv[2]
b = open(src, 'rb').read()          # read-only: the project file is never modified
i = 0
while True:
    i = b.find(b'DE\x03\x04', i)
    if i < 0:
        break
    ver, flag, meth, _a, _b, crc, csz, usz, fl, el = struct.unpack('<HHHIIIIIHH', b[i + 4:i + 34])
    name = b[i + 34:i + 34 + fl].decode('latin-1'); start = i + 34 + fl + el
    data = b[start:start + csz]
    try:
        raw = zlib.decompress(data, -15) if meth == 8 else data
    except zlib.error:
        raw = None
    if raw is not None and len(raw) == usz and name:
        p = os.path.join(out, name); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'wb').write(raw)
        print(f'{usz:9d}  {name}')
        i = start + csz
    else:
        i += 4
