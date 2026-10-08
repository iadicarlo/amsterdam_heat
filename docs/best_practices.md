# Best practices

## Rules

- `data/raw` is read only. Every download writes a `*.source.json` with URL, date and licence. Data is not in git; the scripts rebuild it.
- One grid: RD New (EPSG:28992), 500 m tiles with a 100 m buffer.
- Credit CC BY sources on every map.
- Our changes to SOLWEIG-GPU live in the fork, not in `src/`.
- Run `uv run ruff check` and `uv run pytest` before committing.
- Check recent literature (2021 onwards) before choosing a method, and note the choice in `references/reading_notes.md`.
- Every map says which imagery, LiDAR, weather day and resolution it shows.
- Writing follows [style.md](style.md).

## Pitfalls we hit

| Problem | What to do |
|---|---|
| SOLWEIG reads 0 in the vegetation layer as "no tree", so ground below 0 m NAP gets phantom tree shade | Inputs are lifted by 20 m (`ELEVATION_OFFSET`); never feed raw NAP heights |
| National and most city aerial photos are leaf-off | Use the city's summer infrared flight `infrarood2023` |
| AHN4 is leaf-off | Canopy height is fine, density is too low; keep in mind when comparing with summer measurements |
| PDOK and city GeoJSON carry RD coordinates without a CRS | `read_vector` relabels them; do not reproject |
| PDOK infrared WMS serves only JPEG | Use the city WMS (PNG) for NDVI |
| SOLWEIG-GPU wants local hours 0 to 23, labelled by the end of the hour | `metfile.py` converts KNMI UT hours |
| Upstream sky view factor dropped 4 of 153 patches and used an old vegetation scheme | Fixed in the fork; rerun `scripts/compare_umep.py` after changing shadow code |
| Station wind is too strong for streets | `run_solweig.py` applies GLIDE-SOL by default |
| The 35 C cool-spot threshold belongs to one reference day | Use 1 July 2015, PET averaged 12:00 to 18:00; real heatwaves are stress tests |
| The model uses Schiphol air temperature | The city is warmer; correction planned (roadmap phase 1) |
