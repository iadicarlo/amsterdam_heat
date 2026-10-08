# Roadmap

Everything runs on the MacBook (M4). Updated 2026-10-08.

The aim is one convincing demo for the Gemeente Amsterdam: a district where the heat guidelines fail, with validated numbers and a concrete list of where new trees would fix it. Paris follows with the same pipeline.

## Where we are

Done: data pipeline from open sources, SOLWEIG-GPU on the Mac GPU with Metal kernels (checked against CPU and UMEP), leaf-on trees from the city's summer photo and tree register, PET with GLIDE-SOL street wind, the guideline check (shade on routes, cool spots within 300 m), validation against the HvA measurements, Landsat and ECOSTRESS hot-day series, and one tile (De Pijp).

A 1 m tile takes 43 s the first time and 10 s for every further day, since walls, aspect and sky view factors are kept per tile.

## Phase 1, trustworthy (about 2 weeks of evenings)

1. Keep the static part of each tile across days. Done.
2. Air temperature in the city. The model uses Schiphol air temperature, while streets are warmer. Add an urban heat island correction from the 2015 PANGAEA network and the WUR street stations of summer 2025 and 2026, two of which are in Nieuw-West.
3. Run all of Nieuw-West on the reference hot day (1 July 2015) and stitch the tiles, so cool spots just outside a tile count.
4. Pick the demo neighbourhood inside Nieuw-West with a screen of shade on main routes, distance to cool spots, and vulnerability (elderly residents, income, CBS).
5. Add a real heatwave day (25 July 2019) and check the street stations against the model on hot days in 2025 and 2026.

## Phase 2, useful (about 3 weeks)

1. Plantable space: pavement and squares wide enough for a tree, from the BGT and the summer photo, away from building fronts and existing crowns. Underground cables are not in open data; flag that as the city's check.
2. Tree placement: rank candidate spots by how much they raise shade on the PLUS and HOOFD routes and bring homes within 300 m of a cool spot, weighted towards elderly residents, schools and care homes. Start with a greedy search that reruns the physics locally (fast with the Metal kernel); a learned surrogate only if speed demands it.
3. Before and after: shade percentages and cool-spot coverage for the top 50 or 100 trees.

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
