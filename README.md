# tm-impact-data

Road type tiles for GB motorways and A-roads, used by TM Impact Tools to tell single carriageway from dual, and to find side roads joining a road.

Cut down from **OS Open Roads**. Contains OS data © Crown copyright and database right. Licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

## What's in it

Served by GitHub Pages from the `docs` folder.

| File | What it holds |
|---|---|
| `docs/t/<E>-<N>.json` | One 10 km grid square. E and N are the OS grid easting and northing divided by 10,000, so `32-9.json` covers 320,000 to 330,000 E and 90,000 to 100,000 N |
| `docs/roads.json` | Which squares each road number passes through |
| `docs/meta.json` | When it was built, how many links and junctions, and what the codes mean |

Each square holds:
- `links`: every motorway and A-road link in or crossing the square, as `[id, road number, name, form of way, class, function, trunk, primary, length in m, [x, y, x, y, ...]]`. The line is on the OS grid in metres, simplified to about 5 m. Form of way: S single carriageway, D dual, C collapsed dual, L slip road, R roundabout, X other.
- `junctions`: every point where another road joins a motorway or A-road, as `[x, y, road, joining road's class, joining road, joining road's function]`. Private accesses aren't in OS Open Roads, so they aren't here.

## Refreshing it (about once a year)

OS updates Open Roads about twice a year. Once a year is enough.

1. Open this repo on GitHub and click the **Actions** tab.
2. Click **Build road tiles** in the list on the left.
3. Click **Run workflow** on the right, then the green **Run workflow** button.
4. Wait about 15 to 30 minutes until the run shows a green tick. That's it. GitHub Pages picks up the new files a minute or two later.

The tool keeps each square for 30 days, so changes reach the tool within a month.

## How it's built

`scripts/build_tiles.py`, run by `.github/workflows/build-road-tiles.yml`. It downloads the GB Shapefile from the OS Downloads API, keeps motorway and A-road links, simplifies them, finds the side-road junctions, and writes the squares.
