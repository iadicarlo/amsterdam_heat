# Cables and pipes

Can we see underground utilities in open data before planting? Partly. Checked October 2026 for Nieuw-West (RD 111500, 482000, 118500, 490500). `scripts/get_utilities.py` downloads, `scripts/check_utilities.py` checks a tree plan, `amsterdam_heat.utilities` holds the mask and the check.

## Open sources

| Type | Source | Licence | In the box |
|---|---|---|---|
| Electricity, low, medium and high voltage | Liander Open Data Elektra (ArcGIS feature service) | CC BY 4.0 | 26 609 LS, 7 645 MS, 476 HS lines |
| Gas distribution | Liander Open Data Gas | CC BY 4.0 | 22 640 lines, no pressure or diameter |
| Gas transmission | Gemeente Amsterdam `risicozones/aardgasleidingen` | public | 1 line, none near our plans |
| Sewers | Waternet rioolnetwerk via `api.data.amsterdam.nl/v1/leidingeninfrastructuur` | CC BY | 69 791 pipes with type and diameter, refreshed weekly |
| Street lighting cables | Gemeente Amsterdam, same dataset | CC BY | 337 lines |
| District heating and cold | Vattenfall `STADSWARMTEKOUDE` on Maps Amsterdam open geodata | Maps Amsterdam terms, any lawful use | 1 575 lines, snapshot May 2025 |

Liander left PDOK in December 2025; the data now sits on ArcGIS Online, linked from liander.nl/over-ons/open-data. Liander leaves out house connections and gives no positional accuracy. Liander itself says this does not replace a KLIC notification.

## Not open

- KLIC (Kadaster): only for a registered excavation notification, with conditions on use. The city's copy (`klic_kabels_en_leidingen` and two more tables) returns 403 without a city login.
- Drinking water mains (Waternet): not published.
- Telecom (KPN, Eurofiber and others): not published.
- House connections for electricity and gas.
- BRO holds geology and groundwater, not utilities. GWSW is the sewer data standard; for Amsterdam the open sewer data is the Waternet table above.

## Clearances

Trunk centre to line: 1.0 m for cables and small pipes, 1.5 m for gas mains, 2.0 m for sewers and district heating, 5.0 m for gas transmission (belemmeringengebied in the Bkl). Stedin advises 2.5 m from the tree centre to the edge of the trench, citing CROW publication 280 ("Bomen planten", ZAK.DOC.ST.006.07.18). Municipal cable handbooks point to the CROW Bomenposter and the Norminstituut Bomen table, which we could not open. We report both.

## Our two plans

| | Osdorpplein | De Aker |
|---|---|---|
| Trees | 35 | 189 |
| Within the default clearance | 27 | 90 |
| Within 2.5 m of any line | 30 | 117 |
| Electricity within 1.0 m | 14 | 38 |
| Gas within 1.5 m | 7 | 37 |
| Sewer main within 2.0 m | 14 | 48 |
| District heating within 2.0 m | 2 | 2 |

Most conflicts are cables and sewers under the same pavements where the shade is needed. A trunk can often move a few metres, so the next step is to pass `utility_mask` into the candidate search and plan again. Drinking water and telecom are still missing, so every spot still needs the city's KLIC check.
