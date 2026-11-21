# tm-impact-data

Open map data for TM Impact Tools, cut into small tiles and served by GitHub Pages:

- **Road tiles** from OS Open Roads: single or dual carriageway, and side roads joining a road.
- **Street reference (USRN) tiles** from OS Open USRN: the street IDs used for Street Manager permits and TTROs.
- **Sites and background tiles** from OS OpenMap - Local: schools, hospitals and other sites for the impact check, and a map background for drawings along motorways and trunk roads.

Contains OS data © Crown copyright and database right. Licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

## Road tiles (OS Open Roads)

Served by GitHub Pages from the `docs` folder.

| File | What it holds |
|---|---|
| `docs/t/<E>-<N>.json` | One 10 km grid square. E and N are the OS grid easting and northing divided by 10,000, so `32-9.json` covers 320,000 to 330,000 E and 90,000 to 100,000 N |
| `docs/roads.json` | Which squares each road number passes through |
| `docs/meta.json` | When it was built, how many links and junctions, and what the codes mean |

Each square holds:
- `links`: every motorway and A-road link in or crossing the square, as `[id, road number, name, form of way, class, function, trunk, primary, length in m, [x, y, x, y, ...]]`. The line is on the OS grid in metres, simplified to about 5 m. Form of way: S single carriageway, D dual, C collapsed dual, L slip road, R roundabout, X other.
- `junctions`: every point where another road joins a motorway or A-road, as `[x, y, road, joining road's class, joining road, joining road's function]`. Private accesses aren't in OS Open Roads, so they aren't here.

## Street reference tiles (OS Open USRN)

| File | What it holds |
|---|---|
| `docs/u/<E>-<N>.json` | One **5 km** grid square. E and N are the easting and northing divided by 5,000. Every street crossing it, cut to the square plus 25 m, as `[usrn, type, [line, ...]]` |
| `docs/ui/<NNN>.json` | Look-up by USRN. NNN is the first 3 digits of the USRN padded to 8 digits. Each entry is `usrn: [type, minX, minY, maxX, maxY]`, so the tool knows which squares to fetch |
| `docs/usrn-meta.json` | When it was built, counts, and what the codes mean |

Type: D Designated Street Name, O Officially Described Street, N Numbered Street, U Unofficial Street Name, A Street for addressing purposes only. OS Open USRN has no street names. Take names and road numbers from the road tiles by position.

## Sites and background tiles (OS OpenMap - Local)

| File | What it holds |
|---|---|
| `docs/s/<E>-<N>.json` | One 10 km square, same grid as the road tiles, all of GB. `sites`: FunctionalSite as `[name, classification, centreX, centreY, [polygon, ...]]`. `buildings`: ImportantBuilding as `[name, buildingTheme, classification, centreX, centreY, [polygon, ...]]` |
| `docs/bg/<E>-<N>.json` | One **5 km** square, only along motorways and trunk roads (250 m either side). `layers`: building, woodland, water, tidal, foreshore, waterline, rail. Buildings that touch the corridor are kept whole, the rest is cut to it |
| `docs/openmap-meta.json` | When it was built, layers found, counts and sizes |

All of GB as background would not fit in GitHub Pages' 1 GB, so it only covers the corridor. To widen it, change `CORRIDOR_M` in `scripts/build_openmap.py`. The build stops without saving if the site would go over 950 MB.

## How the USRN and OpenMap lines are stored

To keep files small, every line or ring is one list: the first point in full, then each next point as the change from the one before, in whole metres on the OS grid. `[x0, y0, dx1, dy1, dx2, dy2, ...]`. To read it, start at x0, y0 and keep adding. A polygon is a list of rings, outer ring first.

## Roadspace place list (clash checker)

| File | What it holds |
|---|---|
| `docs/rs/roadspace-<first 16 of SHA-256>.b64` | The roadspace clash checker's gazetteer (junctions, marker posts every 0.3 km and place names by road), gzipped JSON as base64. Built from OS Open Names and the marker post data in the tm-impact-tools repo |

The Worker fetches this file on first use and checks it against the SHA-256 written into the Worker, so a changed copy is never used. Each version has its own file name; leave old ones in place so older Worker versions keep working. Publish a new one with `python tools/publish_roadspace_data.py <this repo>` from tm-impact-tools.

## Refreshing it (about once a year)

OS updates Open Roads about twice a year. Once a year is enough.

Run the three builds in this order, one at a time. Wait for each green tick before starting the next.

1. Open this repo on GitHub and click the **Actions** tab.
2. Click **Build road tiles** in the list on the left.
3. Click **Run workflow** on the right, then the green **Run workflow** button. About 15 to 30 minutes.
4. Do the same for **Build USRN tiles**. About 20 to 40 minutes.
5. Do the same for **Build OpenMap Local tiles**. This one is the biggest download, about 1 to 3 hours. It needs the road tiles, so always run it after step 3.

GitHub Pages picks up the new files a minute or two after each green tick. If a run goes red, open it and read the last step's log. The OpenMap build lists the layers it found at the top.

The tool keeps each square for 30 days, so changes reach the tool within a month.

## How it's built

- Road tiles: `scripts/build_tiles.py`, run by `.github/workflows/build-road-tiles.yml`. It downloads the GB Shapefile from the OS Downloads API, keeps motorway and A-road links, simplifies them, finds the side-road junctions, and writes the squares.
- USRN tiles: `scripts/build_usrn.py`, run by `.github/workflows/build-usrn-tiles.yml`. GB GeoPackage, simplified to about 2 m.
- Sites and background: `scripts/build_openmap.py`, run by `.github/workflows/build-openmap-tiles.yml`. GB GeoPackage. Sites simplified to about 2 m, background to about 1 m.
- `scripts/geo_tiles.py` holds the helpers the last two share.
