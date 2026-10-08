# Cables and pipes

Can we see underground utilities in open data before planting? Partly. Checked October 2026 for Nieuw-West (RD 111500, 482000, 118500, 490500). `scripts/get_utilities.py` downloads, `scripts/check_utilities.py` checks a tree plan, `amsterdam_heat.utilities` holds the mask and the check.

## Open sources

| Type | Source | Licence | In the box | Clearance |
|---|---|---|---|---|
| Electricity, LS, MS, HS | Liander Open Data Elektra (ArcGIS) | CC BY 4.0 | 34 730 lines | 1.0 m |
| Electricity stations, LS cabinets | Liander, same service | CC BY 4.0 | 901 points | 2.0 m |
| Gas distribution | Liander Open Data Gas | CC BY 4.0 | 22 640 lines | 1.5 m |
| Gas transmission | Gemeente Amsterdam `risicozones/aardgasleidingen` | public | 1 line | 5.0 m |
| Sewers | Waternet via `api.data.amsterdam.nl/v1/leidingeninfrastructuur` | CC BY | 67 464 pipes | 2.0 m, connections 1.0 m |
| Street lighting cables and ducts | Gemeente Amsterdam, same dataset | CC BY | 373 lines | 1.0 m |
| District heating and cold | Vattenfall on Maps Amsterdam open geodata | Maps Amsterdam terms | snapshot May 2025 | 2.0 m |
| Fire hydrants | BGT plus object `put` (brandkraan) via PDOK | CC0 | 1 707 points | 1.5 m |
| Street cabinets | BGT plus object `kast` via PDOK | CC0 | 1 367 points | 1.5 m |

Liander leaves out house connections and says its data does not replace a KLIC notification.

Hydrants and cabinets are the only open trace of drinking water and telecom. A hydrant sits on a short branch of a water main, so the main runs within a few metres. Amsterdam leaves the cabinet type empty, so electricity, telecom, cable TV and traffic cabinets look the same. We use both as point clearances and do not guess the lines between them.

## Checked and not usable

- Drinking water mains: Waternet publishes none. The national Warmteatlas layer on heat from drinking water (TED) is per buurt, not per pipe. The city table `brandkranen` returns 403; the BGT copy is open.
- Telecom: we found no open route data from KPN, Eurofiber, Delta Fiber or Open Dutch Fiber, only coverage maps. The RDI antenna register shows antennas, not cables.
- OpenStreetMap (ODbL), about the same area: 9 cables, 4 pipelines, 194 hydrants, 118 manholes and 42 cabinets. Fewer than BGT and Liander, so not added.
- The city's `klic_*` tables need a city login. BGT `put` in Amsterdam holds only hydrants, not sewer, water or telecom manholes. BGT `mast` and `sensor` are empty here.

## KLIC orientation request

Kadaster sells an oriëntatieverzoek for €10.50 (2026), at most 2.5 by 2.5 km, delivered within two working days as a zip with the KLIC viewer, deleted after 20 working days. The Wibon (art. 7) allows it for a grondroerder or opdrachtgever preparing excavation, a network operator, or a public body for its own task. A one-off request needs no Mijn Kadaster account; professional excavators need one. The result may not be used to dig, and art. 4 says users treat it as confidential and pass it on only as far as needed for that purpose. So it can guide private planning but cannot go on a public map. The Gemeente can request it for its own work.

## Our two plans

| | Osdorpplein | De Aker |
|---|---|---|
| Trees | 40 | 230 |
| Within the default clearance | 0 | 1 (hydrant at 1.4 m) |
| Within 2.5 m of any line or point | 25 | 97 |

The plans were made with `utility_mask` on the line layers, so only the new hydrant layer adds a conflict. Stedin advises 2.5 m from the tree to the trench edge (CROW publication 280); we report that count too. Every spot still needs a KLIC check before digging.
