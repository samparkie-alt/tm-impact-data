"""Builds the sites and drawing-background tiles for TM Impact Tools from OS OpenMap - Local (GeoPackage, GB).

Usage: python scripts/build_openmap.py <folder with the unzipped OS OpenMap - Local> <output folder, e.g. docs>

Needs the road tiles in <out>/t first (from build_tiles.py). They set the corridor for the background.

Two outputs:

1. Sites, all of GB, for the impact check (schools, hospitals and so on near the works or a diversion):
   <out>/s/<E>-<N>.json   one 10 km square, same grid as the road tiles:
     "sites":     FunctionalSite  [name, classification, centreX, centreY, [polygon, ...]]
     "buildings": ImportantBuilding [name, buildingTheme, classification, centreX, centreY, [polygon, ...]]
   Each feature is in the square that holds its centre. Outlines simplified to about 2 m.

2. Drawing background, along motorways and trunk roads only (all of GB would not fit on GitHub Pages):
   <out>/bg/<E>-<N>.json  one 5 km square (E, N = easting and northing divided by 5,000):
     "layers": {"building": [polygon, ...], "woodland": [...], "water": [...], "tidal": [...],
                "foreshore": [...], "waterline": [line, ...], "rail": [line, ...]}
   Buildings that touch the corridor are kept whole. Woodland, water and rail are cut to the corridor.
   The corridor is CORRIDOR_M either side of every motorway link and trunk road link in the road tiles.

A polygon is a list of rings, outer first. Lines and rings are delta-encoded, see geo_tiles.py.
Layer and field names are matched loosely (case and underscores ignored), and the log lists what it found.
Contains OS data (c) Crown copyright and database right. Open Government Licence v3.0.
"""
import datetime, glob, json, os, shutil, sys

import pyogrio
import shapely
from shapely.strtree import STRtree

from geo_tiles import (find_gpkg, layers, column, lines, polygons, squares, square_box, clip,
                       tile_name, dir_size)

SRC, OUT = sys.argv[1], sys.argv[2]
ROAD_TILE = 10000
BG_TILE = 5000
CORRIDOR_M = 250
SITE_SIMPLIFY_M = 2.0
BG_SIMPLIFY_M = 1.0

SITE_LAYERS = {'functionalsite': 'sites', 'importantbuilding': 'buildings'}
BG_LAYERS = {   # normalised OS layer name -> (our layer, kind)
    'building': ('building', 'keep'),
    'woodland': ('woodland', 'area'),
    'surfacewaterarea': ('water', 'area'),
    'tidalwater': ('tidal', 'area'),
    'foreshore': ('foreshore', 'area'),
    'surfacewaterline': ('waterline', 'line'),
    'railwaytrack': ('rail', 'line'),
}

# ---- What's in the download ----
found = {}            # normalised layer -> [(path, real layer name)]
for path in find_gpkg(SRC):
    for k, real in layers(path).items():
        found.setdefault(k, []).append((path, real))
print('Layers found:', ', '.join(sorted({r for v in found.values() for _, r in v})), flush=True)
missing = [k for k in list(SITE_LAYERS) + list(BG_LAYERS) if k not in found]
if 'functionalsite' in missing or 'building' in missing:
    sys.exit('Key layers missing: %s' % ', '.join(missing))
if missing:
    print('WARNING, these layers are not in the download and will be empty:', ', '.join(missing))


def read(key, bbox=None, cols=None):
    """Read one OS layer from every GeoPackage that has it."""
    import pandas as pd
    parts = []
    for path, real in found.get(key, []):
        df = pyogrio.read_dataframe(path, layer=real, bbox=bbox, columns=cols)
        if len(df):
            parts.append(df)
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else pd.concat(parts, ignore_index=True)


def text(v):
    if v is None:
        return ''
    s = str(v).strip()
    return '' if s.lower() in ('nan', 'none') else s


# ---- 1. Sites ----
site_tiles, site_count = {}, {}
for key, out_key in SITE_LAYERS.items():
    df = read(key)
    if df is None:
        continue
    print(key, len(df), 'features. Fields:', ', '.join(df.columns), flush=True)
    c_name = column(df, 'distinctiveName', 'distinctive_name', 'name')
    c_class = column(df, 'classification')
    c_theme = column(df, 'buildingTheme', 'building_theme')
    geoms = shapely.simplify(df.geometry.values, SITE_SIMPLIFY_M, preserve_topology=True)
    n = 0
    for i, g in enumerate(geoms):
        if g is None or g.is_empty:
            continue
        p = g.representative_point() if g.geom_type not in ('Point', 'MultiPoint') else g.centroid
        cx, cy = int(round(p.x)), int(round(p.y))
        name = text(df[c_name].iat[i]) if c_name else ''
        cls = text(df[c_class].iat[i]) if c_class else ''
        rec = [name] + ([text(df[c_theme].iat[i]) if c_theme else ''] if out_key == 'buildings' else []) + \
              [cls, cx, cy, polygons(g)]
        t = (cx // ROAD_TILE, cy // ROAD_TILE)
        site_tiles.setdefault(t, {'sites': [], 'buildings': []})[out_key].append(rec)
        n += 1
    site_count[out_key] = n
    del df

shutil.rmtree(os.path.join(OUT, 's'), ignore_errors=True)
os.makedirs(os.path.join(OUT, 's'))
for (e, n), body in site_tiles.items():
    body = {'v': 1, 'square': [e * ROAD_TILE, n * ROAD_TILE, ROAD_TILE], **body}
    with open(os.path.join(OUT, 's', tile_name(e, n)), 'w', encoding='utf-8') as fh:
        json.dump(body, fh, separators=(',', ':'), ensure_ascii=False)
print('Sites done:', site_count, flush=True)

# ---- 2. Corridor from the road tiles ----
corridor, seen = [], set()
for f in glob.glob(os.path.join(OUT, 't', '*.json')):
    with open(f, encoding='utf-8') as fh:
        for link in json.load(fh)['links']:
            lid, cls, trunk, xy = link[0], link[4], link[6], link[9]
            if lid in seen or not (cls == 'M' or trunk == 1) or len(xy) < 4:
                continue
            seen.add(lid)
            corridor.append(shapely.LineString(list(zip(xy[0::2], xy[1::2]))))
if not corridor:
    sys.exit('No motorway or trunk links found in %s/t. Run Build road tiles first.' % OUT)
tree = STRtree(corridor)
cells = set()
for g in corridor:
    cells.update(squares(shapely.buffer(g, CORRIDOR_M).bounds, ROAD_TILE))
print(len(corridor), 'motorway and trunk links,', len(cells), '10 km squares to cut', flush=True)

# ---- 3. Background, one 10 km square at a time, split into 5 km squares ----
shutil.rmtree(os.path.join(OUT, 'bg'), ignore_errors=True)
os.makedirs(os.path.join(OUT, 'bg'))
bg_squares, bg_count = 0, {}
for k, (e10, n10) in enumerate(sorted(cells)):
    sq = square_box(e10, n10, ROAD_TILE)
    near = tree.query(shapely.box(*square_box(e10, n10, ROAD_TILE, CORRIDOR_M)))
    if not len(near):
        continue
    zone = shapely.intersection(shapely.union_all(shapely.buffer([corridor[i] for i in near], CORRIDOR_M)),
                                shapely.box(*sq))
    if zone.is_empty:
        continue
    shapely.prepare(zone)
    sub = {}          # (e5, n5) -> {layer: [...]}
    for key, (name, kind) in BG_LAYERS.items():
        if key not in found:
            continue
        df = read(key, bbox=sq, cols=[])
        if df is None:
            continue
        g = df.geometry.values
        g = g[shapely.intersects(zone, g)]
        if not len(g):
            continue
        if kind == 'keep':
            # whole buildings, each in the 5 km square that holds its centre, once
            pts = shapely.point_on_surface(g)
            mine = shapely.contains_xy(shapely.box(*sq), shapely.get_x(pts), shapely.get_y(pts))
            g, pts = g[mine], pts[mine]
            g = shapely.simplify(g, BG_SIMPLIFY_M, preserve_topology=True)
            for geom, p in zip(g, pts):
                t = (int(p.x // BG_TILE), int(p.y // BG_TILE))
                sub.setdefault(t, {}).setdefault(name, []).extend(polygons(geom))
        else:
            g = shapely.simplify(shapely.intersection(g, zone), BG_SIMPLIFY_M, preserve_topology=True)
            for geom in g:
                if geom is None or geom.is_empty:
                    continue
                for t in squares(geom.bounds, BG_TILE):
                    if not (e10 * 2 <= t[0] < e10 * 2 + 2 and n10 * 2 <= t[1] < n10 * 2 + 2):
                        continue
                    piece = clip(geom, t[0], t[1], BG_TILE, 0)
                    out = lines(piece) if kind == 'line' else polygons(piece)
                    if out:
                        sub.setdefault(t, {}).setdefault(name, []).extend(out)
    for (e, n), lay in sub.items():
        for name, v in lay.items():
            bg_count[name] = bg_count.get(name, 0) + len(v)
        body = {'v': 1, 'square': [e * BG_TILE, n * BG_TILE, BG_TILE], 'layers': lay}
        with open(os.path.join(OUT, 'bg', tile_name(e, n)), 'w', encoding='utf-8') as fh:
            json.dump(body, fh, separators=(',', ':'))
        bg_squares += 1
    if (k + 1) % 100 == 0:
        print(k + 1, 'of', len(cells), 'squares,', round(dir_size(os.path.join(OUT, 'bg')) / 1e6), 'MB so far', flush=True)

s_mb, bg_mb, all_mb = dir_size(os.path.join(OUT, 's')) / 1e6, dir_size(os.path.join(OUT, 'bg')) / 1e6, dir_size(OUT) / 1e6
meta = {
    'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
    'source': 'OS OpenMap - Local, GeoPackage, GB (OS Downloads API)',
    'layers_found': sorted({r for v in found.values() for _, r in v}),
    'sites': {'count': site_count, 'squares': len(site_tiles), 'tile_size_m': ROAD_TILE, 'size_mb': round(s_mb, 1),
              'simplified_m': SITE_SIMPLIFY_M,
              'site_fields': ['name', 'classification', 'centreX', 'centreY', 'polygons'],
              'building_fields': ['name', 'buildingTheme', 'classification', 'centreX', 'centreY', 'polygons']},
    'background': {'count': bg_count, 'squares': bg_squares, 'tile_size_m': BG_TILE, 'size_mb': round(bg_mb, 1),
                   'simplified_m': BG_SIMPLIFY_M, 'corridor_m': CORRIDOR_M,
                   'corridor': 'motorway and trunk road links from the road tiles'},
    'geometry': 'polygon = list of rings, outer first; ring or line = x0, y0, then dx, dy, whole metres on the OS grid',
    'credit': 'Contains OS data (c) Crown copyright and database right %d. Open Government Licence v3.0.' % datetime.date.today().year,
}
with open(os.path.join(OUT, 'openmap-meta.json'), 'w', encoding='utf-8') as fh:
    json.dump(meta, fh, indent=1)
open(os.path.join(OUT, '.nojekyll'), 'w').close()
print('Done: sites', round(s_mb, 1), 'MB, background', round(bg_mb, 1), 'MB,', bg_squares, 'squares. Whole site', round(all_mb), 'MB')
if all_mb > 950:
    sys.exit('The whole site is over 950 MB, too close to the 1 GB GitHub Pages limit. Not saving. Lower CORRIDOR_M.')
