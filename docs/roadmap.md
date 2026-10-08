# Roadmap

Everything runs on the MacBook (M4). Updated 2026-10-08.

The aim is one convincing demo for the Gemeente Amsterdam: a district where the heat guidelines fail, with validated numbers and a concrete list of where new trees would fix it. Paris follows with the same pipeline.

## Where we are

Done: data pipeline from open sources, SOLWEIG-GPU on the Mac GPU with Metal kernels (checked against CPU and UMEP), leaf-on trees from the city's summer photo and tree register, PET with GLIDE-SOL street wind, the guideline check (shade on routes, cool spots within 300 m), validation against the HvA measurements, Landsat and ECOSTRESS hot-day series, and one tile (De Pijp).

A 1 m tile takes 43 s the first time and 10 s for every further day, since walls, aspect and sky view factors are kept per tile.

## Phase 1, trustworthy (about 2 weeks of evenings)

1. Keep the static part of each tile across days. Done.
2. Air temperature in the city. Done: an afternoon heat island fitted to 45 street stations (AAMS 2015, WUR 2025 and 2026), about +0.5 K on land and cooler near water, added to PET (docs/uhi.md).
3. Run all of Nieuw-West on the reference hot day (1 July 2015) and stitch the tiles. Done: 177 tiles.
4. Guideline check on the whole district. Done: 10 of 43 main pedestrian streets have 40% shade at 15:00, 41 of 73 neighbourhoods miss 30% on their pavements. Every home is within 300 m of shaded public green, 45% within 300 m of a cool park of 1 ha (docs/guidelines_nieuw-west_2015-07-01.md).
5. Screen for the demo neighbourhood. Done: De Aker-Oost, Middelveldsche Akerpolder and Osdorpplein lead (docs/screen_nieuw-west_2015-07-01.md).
6. Validation against the WUR street globes. Done: no sunlit gap for a small globe (docs/validation_wur.md). Still to do: a real heatwave day (25 July 2019).

## Phase 2, useful

Done for Osdorpplein and De Aker (docs/trees_osdorpplein.md, docs/trees_de-aker.md), with src/amsterdam_heat/planting.py, scripts/plan_trees.py and scripts/verify_trees.py.

1. Plantable space: public pavement and green from the BGT, at least 4 m from facades and 5 m from existing crowns, 1 m inside the pavement. Cables and pipes are not in open data; that stays the city's check.
2. Tree placement: greedy search on the shade added to walking areas at 11:00, 15:00 and 17:00 (15:00 and the main routes count double), as TreePlanter, using the same two half-hour sun positions SOLWEIG uses, until the guideline targets are met. The full model then confirms the result to the percent.
3. Results: 35 trees bring Osdorpplein's main route pavements from 28% to 40% shade at 15:00; 189 trees bring De Aker's pavements from 20% to 30%. Under the new crowns afternoon PET drops by 4.5 to 5.3 C.

Next: tree size and species choice with the city, a second hot day (25 July 2019), and an explanation figure (what makes a spot win).

## Phase 3, pitch (about 1 week)

1. A short Dutch report and an interactive map of the demo district, built with the opengeos tools (leafmap, already used for samgeo) and shared as a web page.
2. Share it with the city's climate adaptation programme, Ingenieursbureau Amsterdam and WUR.

## Phase 4, Paris

La Chapelle and Goutte d'Or (18th), four tiles, 24 June 2026 (40.5 C at Montsouris). New loaders for IGN LiDAR HD, the August 2024 infrared photo, the Paris tree register and Meteo-France. Check against the Plan Climat rule of a cool spot within 7 minutes' walk. See docs/paris_feasibility.md.

## Demo district

Nieuw-West. It is red on the Gemeente's heat risk map, got the most cool spots, and hosted the 2026 cool spot pilot (Osdorp). The phase 1 screen picks the neighbourhood inside it. Zuidoost is the second choice.

The Gemeente's new Koele Groene Stratenkaart (maps.amsterdam.nl/groene_straten, March 2026) marks per street how much greening is still needed. Our tool adds what it does not have: modelled shade and felt temperature per street, and where trees would help most. We score its streets rather than draw a rival map.

## Phase 5, future heat

Rerun the reference day and real heatwaves under 2050 and 2100 climates, using existing downscaled projections only: KNMI'23 scenarios for Amsterdam, DRIAS for Paris, and Copernicus Climate Data Store data (CMIP6, CORDEX, CERRA) through cdsapi or earthlens where needed. Needs a CDS account.

## In the background

- City-wide 1 m runs overnight (about 900 tiles, roughly 11 hours for the first day).
- The sun bias against the HvA globes: test whether it comes from comparing a globe with a standing person.
