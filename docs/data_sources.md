# Data sources: imagery, trees and validation

What we use, what we checked, and what is still to get. Checked on 2026-10-08.

## Aerial imagery

| Source | Season | Bands | Resolution | Access | Use here |
|---|---|---|---|---|---|
| Gemeente Amsterdam `infrarood2023` (map.data.amsterdam.nl WMS) | **Summer, leaf-on** | NIR, red, green | fetched at 0.25 m | open, CC BY 4.0 | **Tree mask (summer NDVI)** |
| Gemeente Amsterdam `lufo2024` | Summer, leaf-on | RGB | fetched at 0.25 m | open, CC BY 4.0 | Visual checks, RGB tree models (DeepForest) |
| Gemeente Amsterdam `lufo2025`, `infrarood2018` to `2022` | Spring, mostly leaf-off | RGB / CIR | | open | Not for vegetation |
| PDOK Beeldmateriaal (national, 2025 and 2026) | Early spring, leaf-off | RGB, CIR | 5 to 8 cm (JPEG only through WMS) | open, CC BY 4.0 | Not for vegetation |
| NSO Satellietdataportaal (Pleiades Neo, SuperView Neo) | Several times a year, including summer | RGB + NIR | 30 to 50 cm | free for Dutch users after registration, not open data | Option for newer summer canopy than 2023; needs Isma's own account and its terms |

The city WMS serves lossless PNG and GeoTIFF, which matters for NDVI. PDOK only serves JPEG.

On the first tile (De Pijp), seasons checked by eye on the same crop over Sarphatipark: `infrarood2023` and `lufo2024` are fully leafed, `lufo2025` and the PDOK 2025 CIR are bare.

## Trees

| Source | What it gives | Notes |
|---|---|---|
| AHN4 DSM minus DTM | Canopy height at 0.5 m | Flown in winter (leaf-off) around 2020 to 2022, so it misses trees planted since and underestimates canopy density |
| Gemeente tree register (`bomen/stamgegevens`, WFS) | Location, species, height class, planting year | Municipal trees only, no private gardens. 1,308 trees in the first tile |
| Summer NDVI from `infrarood2023` | Where there are leaves in summer | Used to confirm AHN canopy and to place register trees AHN missed |

First tile result: AHN alone covers 90% of register trees, summer NDVI 98%, and the combined tree layer 97%.

AHN5 is being flown in parts from 2023; check whether the Amsterdam block is released before scaling up.

## Validation

SOLWEIG predicts mean radiant temperature (Tmrt). Air temperature stations only check the weather forcing, not the radiation model, so the useful references are, in order:

1. **UMEP SOLWEIG in QGIS** on the same tile. Independent implementation of the same model, checks our port and inputs.
2. **WUR / AMS Institute Amsterdam network** (Heusinkveld, Steeneveld): about 30 urban stations and mobile thermal comfort measurements in Amsterdam, including globe or radiation measurements that relate to Tmrt. Needs a data request; also a natural partner when we go to the Gemeente.
3. **Netatmo citizen stations**: dense, but air temperature only and needs a Netatmo developer account (Isma's own).
4. **WOW-NL**: KNMI and RMI plan to open the data during 2026; not yet available as a bulk download.
5. **Landsat land surface temperature** for the broad pattern of hot and cool areas (surface, not air or Tmrt).
