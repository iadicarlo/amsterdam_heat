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
| `zonato2026glidesol` | GLIDE-SOL: global input building and diagnostic UHI around SOLWEIG-GPU (version 2 of the package). Shows how far the same engine scales; their global inputs are coarser than AHN4 and BAG, which is our edge for Amsterdam. |
| `hoppe1999pet` | PET definition (MEMI). Amsterdam's guidelines and the national map are in PET; we use UMEP's PET solver (`src/amsterdam_heat/umep_pet.py`). |
| `brode2011utci` | Operational UTCI polynomial. Converts Tmrt, air temperature, wind and humidity into heat stress classes. |

## Street-level wind (field moving fast, prefer 2021 onwards)

| Key | Role in this project |
|---|---|
| `zonato2026glidesol` | **Used.** Directional wind coefficients from building and tree heights (upwind deceleration, wakes, canopy decay). Dortmund, 25 stations, Aug 2024 to Dec 2025: wind RMSE 2.6 to 0.8 m/s, UTCI RMSE 8.1 to 2.8 C. Implemented in SOLWEIG-GPU; we carry the Schiphol wind to city roughness first. |
| `bernard2023urock` | URock, diagnostic 3D wind model (Rockle method) in UMEP, combined with SOLWEIG in SpatialTC. Heavier, mass consistent; candidate to check GLIDE-SOL against. |
| `snaiki2025windhierarchical` | U-Net plus cGAN surrogate for pedestrian wind from building geometry. Option if we need CFD-like wind fast. |
| `huang2026inpaintingunet` | U-Net surrogate trained on LES (van Reeuwijk group, uDALES), seamless across tiles. Same use. |

## Dutch context

| Key | Role in this project |
|---|---|
| `koopmans2020pet` | The national 1 m PET heat map behind the Klimaateffectatlas. Our baseline: built from AHN3, one idealised hot day, static. We must beat it on currency (yearly imagery), realism (real heatwave days) and the ability to test interventions. Validation report (2020): afternoon mean 12:00 to 18:00 on a 1-in-1000 hot day (1 July 2015); wind reduced with Macdonald, which over-reduced it in central Amsterdam; the Klimaateffectatlas version assumes no wind. |

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
