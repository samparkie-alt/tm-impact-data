"""Shared helpers for the USRN and OpenMap Local tile builds.

Coordinates are on the OS grid in whole metres. To keep files small, every line or ring is written
as one flat list: the first point in full, then each next point as the change from the one before.
    [x0, y0, dx1, dy1, dx2, dy2, ...]
To read it back: x = x0, y = y0, then keep adding the pairs.
"""
import glob, os, re, sys

import pyogrio
import shapely
from shapely.geometry import box


def norm(s):
    """'SurfaceWater_Area' -> 'surfacewaterarea'. Used to match layer and field names whatever case OS uses."""
    return re.sub(r'[^a-z0-9]', '', str(s).lower())


def find_gpkg(src):
    files = sorted(glob.glob(os.path.join(src, '**', '*.gpkg'), recursive=True))
    if not files:
        sys.exit('No GeoPackage found under %s' % src)
    return files


def layers(path):
    """{normalised name: real name} for every layer in a GeoPackage."""
    return {norm(name): name for name, _ in pyogrio.list_layers(path)}


def column(df, *names):
    """The real column name for the first of `names` the table has, matched loosely. None if none."""
    have = {norm(c): c for c in df.columns}
    for n in names:
        if norm(n) in have:
            return have[norm(n)]
    return None


def enc(coords):
    """Delta-encode one line or ring: [x0, y0, dx, dy, ...] in whole metres, dropping repeated points."""
    out, px, py = [], None, None
    for c in coords:                      # some OS data carries a height (Z) value: ignore it
        x, y = int(round(c[0])), int(round(c[1]))
        if px is None:
            out += [x, y]
        elif (x, y) != (px, py):
            out += [x - px, y - py]
        else:
            continue
        px, py = x, y
    return out


def dec(flat):
    """Undo enc(). Used by the self-check."""
    pts, x, y = [], 0, 0
    for i in range(0, len(flat), 2):
        if i == 0:
            x, y = flat[0], flat[1]
        else:
            x += flat[i]; y += flat[i + 1]
        pts.append((x, y))
    return pts


def lines(geom, min_pts=2):
    """Every line in a (Multi)LineString or GeometryCollection, as encoded lists."""
    out = []
    for g in shapely.get_parts(geom):
        if g.is_empty:
            continue
        if g.geom_type == 'LineString':
            e = enc(g.coords)
            if len(e) >= 2 * min_pts:
                out.append(e)
        elif g.geom_type in ('MultiLineString', 'GeometryCollection'):
            out += lines(g, min_pts)
    return out


def polygons(geom):
    """Every polygon in a (Multi)Polygon or GeometryCollection, as a list of encoded rings, outer ring first."""
    out = []
    for g in shapely.get_parts(geom):
        if g.is_empty:
            continue
        if g.geom_type == 'Polygon':
            rings = [enc(g.exterior.coords)] + [enc(r.coords) for r in g.interiors]
            rings = [r for r in rings if len(r) >= 8]          # at least 4 points to close a ring
            if rings:
                out.append(rings)
        elif g.geom_type in ('MultiPolygon', 'GeometryCollection'):
            out += polygons(g)
    return out


def squares(bounds, size):
    """Every grid square of `size` metres that a bounding box touches, as (e, n) indexes."""
    x0, y0, x1, y1 = bounds
    for e in range(int(x0 // size), int(x1 // size) + 1):
        for n in range(int(y0 // size), int(y1 // size) + 1):
            yield e, n


def square_box(e, n, size, pad=0):
    return (e * size - pad, n * size - pad, (e + 1) * size + pad, (n + 1) * size + pad)


def clip(geom, e, n, size, pad):
    return shapely.clip_by_rect(geom, *square_box(e, n, size, pad))


def tile_name(e, n):
    return '%d-%d.json' % (e, n)


def dir_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    return total
