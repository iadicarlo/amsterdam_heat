# Paris

The same pipeline can run in Paris. The open data is close to what we have for Amsterdam.

| Need | Paris source | Notes |
|---|---|---|
| Heights | IGN LiDAR HD, 50 cm surface, terrain and canopy grids | Flown March 2023, leaf-off |
| Leaf-on trees | IGN infrared photo, 20 cm | Flown August 2024 |
| Tree register | opendata.paris.fr `les-arbres` | 220,000 trees, 200,000 with height; no private trees |
| Buildings | IGN BD TOPO | Footprints about 3 m off in the centre; take heights from LiDAR |
| Weather | Meteo-France hourly, Paris-Montsouris | Temperature, humidity, wind, global radiation |
| Vulnerability | INSEE Filosofi 200 m grid, schools, care homes | Open |
| Cool spots | City layers for cool green spaces and facilities | ODbL |

Most City of Paris layers are ODbL, so a combined dataset has to be shared under the same licence. That fits an open project.

## What exists already

Paris has a night air temperature map (2019), a map of over 800 cool spots, a regional heat vulnerability map at block level, and neighbourhood-scale models from Meteo-France. We found no open street-level map of shade, radiant or felt temperature, and no tool that ranks streets for tree planting. The City mentions a shade index in its climate plan; its status needs checking.

The Plan Climat 2024 to 2030 asks for a cool spot within 7 minutes' walk of every resident, the Paris version of Amsterdam's 300 m guideline.

## First area

La Chapelle and Goutte d'Or in the 18th: high poverty, one of the lowest street-tree densities in Paris, and the Lariboisiere weather station next door. First run: four 1 km tiles on 24 June 2026, when Paris-Montsouris reached 40.5 C.

## Validation

Meteo-France stations in Paris give air temperature, and two give radiation. The PANAME campaigns (IPSL, Meteo-France) have dense networks for 2022 and 2023; access terms still to check. We found no open globe temperature data for Paris.

## Sources

- IGN LiDAR HD: https://www.data.gouv.fr/datasets/mnh-lidar-hd
- IGN infrared photos: https://www.data.gouv.fr/datasets/orthophotographies-irc-de-lign/
- Paris trees: https://opendata.paris.fr/explore/dataset/les-arbres/
- Meteo-France hourly data: https://www.data.gouv.fr/datasets/donnees-climatologiques-de-base-horaires
- INSEE Filosofi grid: https://www.insee.fr/fr/statistiques/8735162
- Plan Climat summary: https://cdn.paris.fr/paris/2024/11/22/planclimat_synthese_fr_web_3-0_bassedef-E7Ga.pdf
- PANAME data: https://paname.aeris-data.fr/
