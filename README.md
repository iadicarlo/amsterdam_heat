# amsterdam_heat

Street-level heat stress and shade for Amsterdam, rebuilt every year from open aerial imagery and LiDAR.

The national felt-temperature map in the Klimaateffectatlas is a good start, but it is built from AHN3, covers a single idealised summer day and cannot answer "what if we plant a tree here?". This project aims to:

1. map the current tree canopy from the latest 5 to 8 cm aerial photos (RGB and near infrared) and compare it with AHN4 and the city tree register,
2. compute shade, mean radiant temperature and UTCI at 0.5 to 1 m resolution for real heatwave days with SOLWEIG running on a laptop GPU (Apple Metal),
3. find plantable space from the imagery,
4. rank candidate tree locations by how much heat stress they remove for vulnerable people (care homes, schools, playgrounds, bus stops, elderly residents).

It is a screening tool meant to support planning, not a replacement for detailed site studies.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                  # core environment
uv sync --extra ml       # imagery models (samgeo, DeepForest)
uv run python -c "import torch; print(torch.backends.mps.is_available())"
```

## Layout

```
data/raw        downloaded source data, never edited (not in git)
data/interim    clipped, reprojected, tiled intermediates (not in git)
data/processed  model outputs (not in git)
src/amsterdam_heat  library code
scripts         command line entry points (download, preprocess, run)
notebooks       exploration only, nothing the pipeline depends on
docs            methods notes and best practices
references      bibliography (references.bib) and reading notes
figures         figures for reports and the pitch
external        third party code we patch (for example SOLWEIG-GPU)
```

## Data

All inputs are open data:

| Dataset | Source | Licence |
|---|---|---|
| Aerial photos RGB and CIR, 5 to 8 cm, yearly | Beeldmateriaal Nederland via PDOK | CC BY 4.0 |
| AHN4 point cloud and DSM/DTM, 0.5 m | Rijkswaterstaat / Het Waterschapshuis via PDOK | CC0 |
| 3D BAG buildings | TU Delft 3D geoinformation | CC BY 4.0 |
| BGT large scale topography | Kadaster via PDOK | CC0 |
| Tree register (Bomen) | Gemeente Amsterdam, data.amsterdam.nl | CC0 / open |
| Hourly weather | KNMI station Schiphol (240) | CC BY 4.0 |
| Land surface temperature (validation) | Landsat 8/9 Collection 2 | public domain |

All grids use the Dutch national grid, RD New (EPSG:28992).

## Licence

Code: GPL-3.0 (we build on SOLWEIG-GPU, which is GPL-3.0).
