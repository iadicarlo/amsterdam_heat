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
| WUR MAQ Amsterdam, rooftop | Radiation and weather on the rooftop mast, 1 minute, July 2019 and July 2022 | CC BY-NC 4.0 | Downloaded |
| WUR MAQ Amsterdam, Distributed Network | 23 street stations, air temperature, humidity and wind every 20 minutes, black globe at 6 of them, summers 2025 and 2026 | CC BY-NC 4.0 | In use ([validation_wur.md](validation_wur.md)) |
| PANGAEA Amsterdam network 2015 | Air temperature at 24 stations | CC BY 3.0 | In use (heat island) |
| Landsat 8 and 9, ECOSTRESS | Surface temperature on hot days, 2015 to 2026 | public domain | In use |

## Cables and pipes

See [utilities.md](utilities.md). Used to screen tree spots, not to replace a KLIC check.

| Data | Source | Licence | Notes |
|---|---|---|---|
| Electricity cables, LS, MS, HS | Liander Open Data Elektra (ArcGIS) | CC BY 4.0 | No house connections |
| Gas pipes | Liander Open Data Gas (ArcGIS) | CC BY 4.0 | No pressure or diameter |
| Sewers | Waternet via Gemeente Amsterdam `leidingeninfrastructuur` | CC BY | Weekly, with type and diameter |
| Street lighting cables | Gemeente Amsterdam `leidingeninfrastructuur` | CC BY | |
| Gas transmission | Gemeente Amsterdam `risicozones` | public | |
| District heating and cold | Vattenfall via Maps Amsterdam open geodata | Maps Amsterdam terms | May 2025 |
| Electricity stations and LS cabinets | Liander Open Data Elektra (ArcGIS) | CC BY 4.0 | Points |
| Street lighting ducts | Gemeente Amsterdam `leidingeninfrastructuur` | CC BY | |
| Fire hydrants, street cabinets | BGT plus objects `put` and `kast` via PDOK | CC0 | Proxy for water mains and telecom; cabinet type left empty |
