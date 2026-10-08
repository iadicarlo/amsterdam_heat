# Reading notes

One line per paper on why it matters here. Keys match `references.bib`. Every entry was checked against CrossRef or arXiv when added (`scripts/build_bib.py`).

## Radiation and thermal comfort physics

| Key | Role in this project |
|---|---|
| `lindberg2008solweig` | Original SOLWEIG model: shadows, sky view factor and mean radiant temperature (Tmrt) from a DSM. The physics we run. |
| `lindberg2011vegetation` | Adds trees (canopy DSM and trunk zone) to SOLWEIG and evaluates shading by vegetation. Needed because trees drive most of the cooling. |
| `wallenberg2020anisotropic` | Anisotropic diffuse sky radiation, part of SOLWEIG 2022a which SOLWEIG-GPU implements. |
| `lindberg2018umep` | UMEP, the QGIS toolbox SOLWEIG lives in. Reference implementation for checking our GPU results. |
| `kamath2026solweiggpu` | SOLWEIG 2022a in PyTorch (GPL-3.0). Our starting code, patched to run on Apple MPS. |
| `brode2011utci` | Operational UTCI polynomial. Converts Tmrt, air temperature, wind and humidity into heat stress classes. |

## Dutch context

| Key | Role in this project |
|---|---|
| `koopmans2020pet` | The national 1 m PET heat map behind the Klimaateffectatlas. Our baseline: built from AHN3, one idealised hot day, static. We must beat it on currency (yearly imagery), realism (real heatwave days) and the ability to test interventions. |

## Machine learning surrogates and tree placement

| Key | Role in this project |
|---|---|
| `briegel2023unet` | U-Net trained on SOLWEIG output predicts Tmrt at 1 m, about 22 times faster (MAE about 2.4 K). Template for our fast what-if surrogate. |
| `briegel2025projections` | Same group scales the surrogate to city-wide climate projections of street-level heat stress. Shows the approach holds up at city scale. |
| `wallenberg2022treeplanter` | TreePlanter v1.0: hill climbing over SOLWEIG rasters to place trees that lower Tmrt the most. Non-ML baseline for the optimiser. |
| `schrodi2023treeplacement` | Neural Tmrt model plus iterated local search for tree placement over large areas. Closest prior work to our optimiser; check for code before reimplementing. |
| `ronneberger2015unet` | Original U-Net architecture. |

## Imagery models

| Key | Role in this project |
|---|---|
| `tolan2024canopy` | Meta/WRI canopy height from RGB with a DINOv2 backbone, 1 m global map and open weights. Use to update tree heights where AHN4 is out of date. |
| `weinstein2020deepforest` | DeepForest, pretrained RGB tree crown detector. Candidate for detecting individual trees in the 8 cm aerial photos. |
| `kirillov2023sam` | Segment Anything. Zero-shot segmentation backbone. |
| `wu2023samgeo` | samgeo, SAM wrapped for GeoTIFFs with text prompts. Candidate for plantable space (pavement, squares, parking). |

## Still to read or chase

- Code for `schrodi2023treeplacement`: no repository linked on arXiv; ask the authors.
- Citizen weather station data for validation in Amsterdam (Netatmo based studies).
- Landsat land surface temperature over Amsterdam during the July 2019 and 2022 heatwaves.
