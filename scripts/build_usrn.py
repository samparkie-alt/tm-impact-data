"""Builds the street reference (USRN) tiles for TM Impact Tools from OS Open USRN (GeoPackage, GB).

Usage: python scripts/build_usrn.py <folder with the unzipped OS Open USRN> <output folder, e.g. docs>

OS Open USRN has one feature per street (field names from the OS Open USRN technical specification):
  usrn         Unique Street Reference Number, the ID Street Manager permits and TTROs use
  street_type  Designated Street Name, Officially Described Street, Numbered Street, Unofficial Street Name
               (and, in some releases, Street for addressing purposes only)
  geometry     MultiLineString, the street's extent
It has no street names. Names and road numbers come from OS Open Roads by matching position.

Output:
  <out>/u/<E>-<N>.json   one 5 km grid square (E, N = easting and northing divided by 5,000), holding
                         every street that crosses it, cut to the square plus 25 m:
                         {"streets": [[usrn, type, [line, line, ...]], ...]}
  <out>/ui/<NNN>.json    look-up by USRN, split by its first 3 digits (padded to 8 digits):
                         {"usrn": [type, minX, minY, maxX, maxY]} so the tool knows which squares to fetch
  <out>/usrn-meta.json   date, counts, codes and credit

Lines are delta-encoded, see geo_tiles.py.
Contains OS data (c) Crown copyright and database right. Open Government Licence v3.0.
"""
import datetime, json, os, shutil, sys

import pyogrio
import shapely

from geo_tiles import find_gpkg, column, lines, squares, clip, tile_name, dir_size

SRC, OUT = sys.argv[1], sys.argv[2]
TILE = 5000           # 5 km squares: towns have a lot of streets
PAD = 25              # keep 25 m over each edge so a click near the edge still finds the street
SIMPLIFY_M = 2.0
TYPES = {'Designated Street Name': 'D', 'Officially Described Street': 'O', 'Numbered Street': 'N',
         'Unofficial Street Name': 'U', 'Street for addressing purposes only': 'A'}

tiles, index = {}, {}
count, skipped = 0, 0
type_count = {}
for path in find_gpkg(SRC):
    for name, gtype in pyogrio.list_layers(path):
        if not gtype or 'line' not in str(gtype).lower():
            print('Skipping layer', name, gtype)
            continue
        print('Reading', path, 'layer', name, flush=True)
        df = pyogrio.read_dataframe(path, layer=name)
        cu, ct = column(df, 'usrn'), column(df, 'street_type', 'streetType')
        if not cu or not ct:
            sys.exit('Fields usrn / street_type not found in %s. Fields are: %s' % (name, ', '.join(df.columns)))
        print(len(df), 'streets. Fields:', ', '.join(df.columns), flush=True)
        geoms = shapely.simplify(df.geometry.values, SIMPLIFY_M, preserve_topology=False)
        for usrn, st, g in zip(df[cu].values, df[ct].values, geoms):
            if g is None or g.is_empty:
                skipped += 1
                continue
            u = int(usrn)
            t = TYPES.get(str(st).strip(), 'X')
            type_count[t] = type_count.get(t, 0) + 1
            b = g.bounds
            for e, n in squares(b, TILE):
                part = lines(clip(g, e, n, TILE, PAD))
                if part:
                    tiles.setdefault((e, n), []).append([u, t, part])
            index.setdefault(str(u).zfill(8)[:3], {})[str(u)] = [t] + [int(round(v)) for v in b]
            count += 1
            if count % 200000 == 0:
                print(count, 'streets done', flush=True)

if count == 0:
    sys.exit('No streets read. Check the download.')

for sub in ('u', 'ui'):
    shutil.rmtree(os.path.join(OUT, sub), ignore_errors=True)
    os.makedirs(os.path.join(OUT, sub))
for (e, n), streets in tiles.items():
    body = {'v': 1, 'square': [e * TILE, n * TILE, TILE], 'streets': streets}
    with open(os.path.join(OUT, 'u', tile_name(e, n)), 'w', encoding='utf-8') as fh:
        json.dump(body, fh, separators=(',', ':'))
for k, v in index.items():
    with open(os.path.join(OUT, 'ui', k + '.json'), 'w', encoding='utf-8') as fh:
        json.dump(v, fh, separators=(',', ':'))

size_mb = (dir_size(os.path.join(OUT, 'u')) + dir_size(os.path.join(OUT, 'ui'))) / 1e6
meta = {
    'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
    'source': 'OS Open USRN, GeoPackage, GB (OS Downloads API)',
    'streets': count, 'skipped_empty': skipped, 'by_type': type_count, 'squares': len(tiles),
    'size_mb': round(size_mb, 1), 'tile_size_m': TILE, 'edge_overlap_m': PAD, 'simplified_m': SIMPLIFY_M,
    'tile_fields': ['usrn', 'type', 'lines'], 'index_fields': ['type', 'minX', 'minY', 'maxX', 'maxY'],
    'line_encoding': 'x0, y0, then dx, dy for each next point, whole metres on the OS grid',
    'codes': {'type': {v: k for k, v in TYPES.items()} | {'X': 'Other'}},
    'credit': 'Contains OS data (c) Crown copyright and database right %d. Open Government Licence v3.0.' % datetime.date.today().year,
}
with open(os.path.join(OUT, 'usrn-meta.json'), 'w', encoding='utf-8') as fh:
    json.dump(meta, fh, indent=1)
open(os.path.join(OUT, '.nojekyll'), 'w').close()
print('Done:', count, 'streets,', len(tiles), 'squares,', round(size_mb, 1), 'MB')
if size_mb > 700:
    sys.exit('Output is over 700 MB, too close to the 1 GB GitHub Pages limit. Not saving.')
