# Data sources

Checked October 2026. All grids in RD New (EPSG:28992).

## Model inputs

| Data | Source | Licence | Notes |
|---|---|---|---|
| Heights, 0.5 m | AHN4 via PDOK | CC0 | Flown in winter, leaf-off |
| Buildings | BAG via PDOK | CC0 | Footprints |
| Roads, footways, green | BGT via PDOK | CC0 | Current objects only |
| Summer infrared photo | Gemeente Amsterdam `infrarood2023` | CC BY 4.0 | Leaf-on; used for the tree mask (NDVI) |
| Trees | Gemeente Amsterdam tree register | open | Municipal trees only, with height class |
| Pedestrian routes | Gemeente Amsterdam plus- en hoofdnetten | open | `VOET` = PLUS or HOOFD |
| Neighbourhoods | Gemeente Amsterdam gebieden | open | |
| Weather | KNMI Schiphol (240), hourly | CC BY 4.0 | |

Most aerial photos (PDOK, and the city's spring flights) are leaf-off and miss street trees. Of the city layers, `infrarood2023` and `lufo2024` are summer flights.

On the De Pijp tile, AHN alone covers 90% of register trees, summer NDVI 98%, and the combined tree layer 97%.

## Validation

| Data | What | Licence | Status |
|---|---|---|---|
| HvA Thermal comfort Amsterdam | Globe temperature and weather at 21 sites, 12 summer afternoons, 2015 and 2016 | CC BY 4.0 | In use |
| UMEP SOLWEIG code | Shadows and sky view factors on the same inputs | GPL-3.0 | In use |
| WUR / AMS station network | 24 stations since 2014, some with globe temperature | CC BY-NC 4.0 | To request (maq-observations.nl) |
| Landsat surface temperature | Broad hot and cool pattern | public domain | Not yet used |
