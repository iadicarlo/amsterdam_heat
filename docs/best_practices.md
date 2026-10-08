# Best practices

Working rules for this project. Short on purpose.

## Data

- `data/raw` is read only. Every file there comes from a download script in `scripts/` that records the source URL, date fetched and licence in a sidecar `*.source.json`. Never edit raw data by hand.
- One coordinate system: RD New, EPSG:28992. Reproject on the way in, never inside the model.
- One tiling scheme: 500 m tiles aligned to round RD coordinates, with a 100 m buffer so shadows from buildings outside the tile are included. Crop the buffer off after the run.
- Rasters as Cloud Optimized GeoTIFF, model output as NetCDF (xarray) with units and provenance in the attributes.
- Data is not committed to git. The pipeline must be able to rebuild everything from the download scripts.

## Licences and attribution

- Aerial photos (Beeldmateriaal), 3D BAG and KNMI data are CC BY 4.0: credit them on every map and in the README.
- SOLWEIG-GPU is GPL-3.0, so this repository is GPL-3.0 too. Keep our patches in a fork, not copied into `src/`.
- Check the licence of every pretrained model before using its output in anything shared with the Gemeente.

## Known pitfalls (found on the first tile)

- **Ground below sea level.** SOLWEIG, like UMEP, uses 0 in the vegetation surface to mean "no tree". Ground below 0 m NAP then sees phantom vegetation above it and is shaded. Most of Amsterdam is below NAP. `tile_inputs.py` lifts all elevations by `ELEVATION_OFFSET` (20 m), which leaves the physics unchanged. Never feed raw NAP heights to SOLWEIG.
- **Aerial photos are leaf-off.** The national Beeldmateriaal flights are in early spring, so deciduous trees are bare and NDVI misses most street trees. Do not use spring NDVI to decide where trees are. Use AHN height (with a size filter), the city tree register, or a summer source.
- **AHN4 is leaf-off too.** It was flown in winter, so canopy height is fine but canopy density is underestimated. Keep this in mind when comparing shade with summer observations.
- **BAG GeoJSON from PDOK has RD coordinates but no CRS member.** GeoJSON readers then assume WGS84. Always `set_crs(28992, allow_override=True)`.
- **PDOK CIR WMS serves JPEG only.** We georeference it from the request box.
- **Met file hours.** SOLWEIG-GPU wants local clock hours 0 to 23 within one date, labelled by the end of the hour. KNMI hours are UT and also end-of-hour.

## Modelling

- Before trusting the GPU port, reproduce a UMEP/SOLWEIG reference run on one tile and compare Tmrt cell by cell. Write down the tolerance we accept.
- Apple MPS has no float64. Run in float32 and check the CPU float64 result on one tile to confirm the difference is negligible.
- Use real heatwave days (KNMI Schiphol hourly data, for example 25 July 2019 and 19 July 2022), not only an idealised day, and state which days every map shows.
- Treat the ML surrogate as a speed-up for what-if questions. The physics model is the reference; report surrogate error against it on held-out neighbourhoods, not random pixels.
- Validate against independent observations (citizen weather stations, Landsat land surface temperature for the broad pattern) and say clearly what each comparison can and cannot show.

## Code

- Library code in `src/amsterdam_heat`, thin command line scripts in `scripts/`, notebooks for exploration only.
- Fix random seeds and log package versions (`uv.lock` is committed).
- Small functions with docstrings that state units and array shapes.
- `uv run ruff check` and `uv run pytest` before committing.

## Communication

- The product is a screening tool for planners. Say what it is not: not a replacement for site studies, not a forecast.
- Every map states the date of the imagery and LiDAR, the weather day, and the resolution.
- Plain Dutch or English for the Gemeente, no jargon without explanation.

## Writing style for everything in this repo

- Write as Isma, in a plain human voice.
- No em dashes or en dashes in prose. Use commas, colons, parentheses or separate sentences.
- Avoid stock phrasing such as delve, unravel, nuanced, comprehensive, underscores, leverage, shed light on.
- No mention of AI assistants anywhere: no co-author trailers, no "generated with" lines, no assistant credits in commits, pull requests, docs or code comments.
