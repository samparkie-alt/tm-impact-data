"""Builds the road type tiles for TM Impact Tools from OS Open Roads (ESRI Shapefile, GB).

Usage: python scripts/build_tiles.py <folder with the unzipped OS Open Roads> <output folder, e.g. docs>

What it keeps, for every motorway and A-road link:
  road number, name, form of way (single, dual, collapsed dual, slip, roundabout), classification,
  function, trunk road and primary route flags, length, and the line simplified to about 5 m.
It also keeps every point where another road joins a motorway or A-road (side-road junctions).

Output, one small JSON file per 10 km grid square:  <out>/t/<E>-<N>.json  where E and N are the
OS grid easting and northing divided by 10,000 (e.g. 32-9 covers 320000-330000 E, 90000-100000 N).
Plus <out>/roads.json (which squares each road passes through) and <out>/meta.json (date, counts, credit).

Field names are from the OS Open Roads technical specification, Shapefile overview, RoadLink:
  identifier, class, function, roadNumber, name1, formOfWay, length, primary, trunkRoad, startNode, endNode.

Contains OS data (c) Crown copyright and database right. Open Government Licence v3.0.
"""
import datetime, glob, hashlib, json, os, sys
import shapefile  # pyshp

SRC, OUT = sys.argv[1], sys.argv[2]
TILE = 10000          # 10 km squares
SIMPLIFY_M = 5.0      # Douglas-Peucker tolerance in metres
KEEP_CLASS = {'Motorway', 'A Road'}
FOW = {'Single Carriageway': 'S', 'Dual Carriageway': 'D', 'Collapsed Dual Carriageway': 'C',
       'Slip Road': 'L', 'Roundabout': 'R'}
CLS = {'Motorway': 'M', 'A Road': 'A', 'B Road': 'B', 'Classified Unnumbered': 'C', 'Unclassified': 'U',
       'Not Classified': 'N', 'Unknown': 'X'}
FUN = {'Motorway': 'M', 'A Road': 'A', 'B Road': 'B', 'Minor Road': 'm', 'Local Road': 'l',
       'Local Access Road': 'a', 'Restricted Local Access Road': 'r', 'Secondary Access Road': 's'}


def yes(v):
    """Shapefile booleans can arrive as True/False, 'T'/'F', 'true'/'false' or 1/0."""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ('t', 'true', 'y', 'yes', '1')


def simplify(pts, tol):
    """Douglas-Peucker, iterative, keeps the end points."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    t2 = tol * tol
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]; bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if L2 == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
                d2 = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d2 > best:
                best, bi = d2, i
        if best > t2:
            keep[bi] = True
            stack.append((a, bi)); stack.append((bi, b))
    return [p for p, k in zip(pts, keep) if k]


def tiles_for(pts):
    """Every 10 km square the line passes through (sampled every 1 km along each segment)."""
    out = set()
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] or pts):
        n = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) // 1000) + 1)
        for k in range(n + 1):
            x = x0 + (x1 - x0) * k / n; y = y0 + (y1 - y0) * k / n
            out.add((int(x // TILE), int(y // TILE)))
    return out


def readers(kind):
    files = sorted(glob.glob(os.path.join(SRC, '**', '*%s*.shp' % kind), recursive=True))
    if not files:
        sys.exit('No %s shapefiles found under %s' % (kind, SRC))
    for f in files:
        yield f, shapefile.Reader(f, encoding='utf-8', encodingErrors='replace')


def field_index(r, names):
    have = [f[0] for f in r.fields[1:]]
    low = {h.lower(): i for i, h in enumerate(have)}
    idx = {}
    for n in names:
        if n.lower() not in low:
            sys.exit('Field %s not found. Fields are: %s' % (n, ', '.join(have)))
        idx[n] = low[n.lower()]
    return idx


FIELDS = ['identifier', 'class', 'function', 'roadNumber', 'name1', 'formOfWay', 'length', 'primary',
          'trunkRoad', 'startNode', 'endNode']

# ---- Pass 1: motorway and A-road links, with their geometry ----
tiles = {}            # (e10, n10) -> {'links': [...], 'junctions': [...]}
roads = {}            # road number -> set of tiles
node_pos = {}         # node id -> (x, y) for nodes on kept links
node_roads = {}       # node id -> set of road numbers of kept links touching it
kept = 0
for f, r in readers('RoadLink'):
    ix = field_index(r, FIELDS)
    for sr in r.iterShapeRecords():
        rec = sr.record
        cls = rec[ix['class']]
        if cls not in KEEP_CLASS:
            continue
        pts = [(float(x), float(y)) for x, y in sr.shape.points]
        if len(pts) < 2:
            continue
        num = (rec[ix['roadNumber']] or '').strip()
        name = (rec[ix['name1']] or '').strip()
        sn, en = rec[ix['startNode']], rec[ix['endNode']]
        for nid, p in ((sn, pts[0]), (en, pts[-1])):
            node_pos[nid] = (round(p[0]), round(p[1]))
            node_roads.setdefault(nid, set()).add(num or name)
        simp = simplify(pts, SIMPLIFY_M)
        flat = [v for p in simp for v in (round(p[0]), round(p[1]))]
        lid = hashlib.sha1(str(rec[ix['identifier']]).encode()).hexdigest()[:10]
        link = [lid, num, name, FOW.get(rec[ix['formOfWay']], 'X'), CLS.get(cls, 'X'),
                FUN.get(rec[ix['function']], 'X'), 1 if yes(rec[ix['trunkRoad']]) else 0,
                1 if yes(rec[ix['primary']]) else 0, round(float(rec[ix['length']] or 0)), flat]
        for t in tiles_for(simp):
            tiles.setdefault(t, {'links': [], 'junctions': []})['links'].append(link)
            if num:
                roads.setdefault(num, set()).add(t)
        kept += 1
    print(f, 'kept so far', kept, flush=True)

# ---- Pass 2: every other road that touches a kept node is a side-road junction ----
seen = set()
junctions = 0
for f, r in readers('RoadLink'):
    ix = field_index(r, FIELDS)
    for rec in r.iterRecords():
        cls = rec[ix['class']]
        num = (rec[ix['roadNumber']] or '').strip()
        name = (rec[ix['name1']] or '').strip()
        me = num or name
        for nid in (rec[ix['startNode']], rec[ix['endNode']]):
            on = node_roads.get(nid)
            if not on:
                continue
            x, y = node_pos[nid]
            for road in on:
                # a road's own links (including its roundabouts and slips that carry its number) are not side roads
                if road == me:
                    continue
                key = (nid, road, me)
                if key in seen:
                    continue
                seen.add(key)
                t = (int(x // TILE), int(y // TILE))
                tiles.setdefault(t, {'links': [], 'junctions': []})['junctions'].append(
                    [x, y, road, CLS.get(cls, 'X'), me, FUN.get(rec[ix['function']], 'X')])
                junctions += 1
    print(f, 'junctions so far', junctions, flush=True)

# ---- Write ----
os.makedirs(os.path.join(OUT, 't'), exist_ok=True)
for (e, n), body in tiles.items():
    body = {'v': 1, 'square': [e * TILE, n * TILE, TILE], **body}
    with open(os.path.join(OUT, 't', '%d-%d.json' % (e, n)), 'w', encoding='utf-8') as fh:
        json.dump(body, fh, separators=(',', ':'), ensure_ascii=False)
with open(os.path.join(OUT, 'roads.json'), 'w', encoding='utf-8') as fh:
    json.dump({k: sorted('%d-%d' % t for t in v) for k, v in sorted(roads.items())}, fh, separators=(',', ':'))
meta = {
    'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
    'source': 'OS Open Roads, ESRI Shapefile, GB (OS Downloads API)',
    'links': kept, 'junctions': junctions, 'squares': len(tiles),
    'tile_size_m': TILE, 'simplified_m': SIMPLIFY_M,
    'link_fields': ['id', 'roadNumber', 'name', 'formOfWay', 'class', 'function', 'trunk', 'primary', 'length_m', 'xy'],
    'junction_fields': ['x', 'y', 'road', 'joining_class', 'joining_road', 'joining_function'],
    'codes': {'formOfWay': {v: k for k, v in FOW.items()} | {'X': 'Other'},
              'class': {v: k for k, v in CLS.items()}, 'function': {v: k for k, v in FUN.items()}},
    'credit': 'Contains OS data (c) Crown copyright and database right %d. Open Government Licence v3.0.' % datetime.date.today().year,
}
with open(os.path.join(OUT, 'meta.json'), 'w', encoding='utf-8') as fh:
    json.dump(meta, fh, indent=1, ensure_ascii=False)
open(os.path.join(OUT, '.nojekyll'), 'w').close()
print('Done:', kept, 'links,', junctions, 'junctions,', len(tiles), 'squares')
