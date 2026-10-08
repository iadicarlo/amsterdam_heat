# Roadmap

Everything runs on the MacBook (M4). Updated 2026-10-08.

The aim is one convincing demo for the Gemeente Amsterdam: a district where the heat guidelines fail, with validated numbers and a concrete list of where new trees would fix it. Paris follows with the same pipeline.

## Where we are

Done: data pipeline from open sources, SOLWEIG-GPU on the Mac GPU (checked against CPU and UMEP), leaf-on trees from the city's summer photo and tree register, PET with GLIDE-SOL street wind, the guideline check (shade on routes, cool spots within 300 m), one tile (De Pijp).

Running: validation against the HvA measurements, full-day timing of the fused Metal kernel.

## Phase 0, now (this week)

1. Finish the HvA validation and write it up.
2. Merge the Metal kernel if the full-day timing confirms the gain; the background agent then fuses the hourly sky-patch code.
3. Request the WUR/AMS station data (maq-observations.nl).

## Phase 1, trustworthy (about 2 weeks of evenings)

1. Air temperature in the city. The model uses Schiphol air temperature, while the squares are warmer. Add a simple urban heat island correction and check it against the HvA and WUR data.
2. Several tiles at once. Run and stitch neighbouring tiles so cool spots just outside a tile count, and remove the tile-edge bias in the 300 m check.
3. Pick the demo district with a quick screen of all of Amsterdam: tree density from the register, the national PET map, and vulnerability (elderly residents, income, CBS). Candidates: Nieuw-West (Slotermeer, Geuzenveld), Bijlmer, Indische Buurt.
4. Run the demo district on the reference hot day (1 July 2015) and a real heatwave (25 July 2019).

## Phase 2, useful (about 3 weeks)

1. Plantable space: pavement and squares wide enough for a tree, from the BGT and the summer photo, away from building fronts and existing crowns. Underground cables are not in open data; flag that as the city's check.
2. Tree placement: rank candidate spots by how much they raise shade on the PLUS and HOOFD routes and bring homes within 300 m of a cool spot, weighted towards elderly residents, schools and care homes. Start with a greedy search that reruns the physics locally (fast with the Metal kernel); a learned surrogate only if speed demands it.
3. Before and after: shade percentages and cool-spot coverage for the top 50 or 100 trees.

## Phase 3, pitch (about 1 week)

1. A short Dutch report and an interactive map of the demo district.
2. Share it with the city's climate adaptation programme, Ingenieursbureau Amsterdam and WUR.

## Phase 4, Paris

La Chapelle and Goutte d'Or (18th), four tiles, 24 June 2026 (40.5 C at Montsouris). New loaders for IGN LiDAR HD, the August 2024 infrared photo, the Paris tree register and Meteo-France. Check against the Plan Climat rule of a cool spot within 7 minutes' walk. See docs/paris_feasibility.md.

## In the background

- Metal acceleration of the remaining hourly code.
- City-wide 1 m runs overnight once the kernel is merged (about 900 tiles).

## Demo district

Chosen in phase 1: the district with the clearest gap against the guidelines that is also a city priority (Nieuw-West and Zuidoost have their own master plans in the 2026 coalition agreement).
