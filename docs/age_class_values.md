# Specific heat demand of the age classes

Where the EFH and MFH values in
[`src/fheat_de/data/building_age_classes.json`](../src/fheat_de/data/building_age_classes.json)
(`waerme_efh_kwh_m2a`, `waerme_mfh_kwh_m2a`) come from and how they were derived.
[`scripts/derive_age_classes.py`](../scripts/derive_age_classes.py) repeats every
step below and checks the JSON against the source.

## Use in F|Heat

The values are the specific heat demand [kWh/(m²·a)] of a residential building
by age class. F|Heat multiplies them by the building's floor area:

- `heat_demand_basis="calculated"` (the default): every NRW building with
  load profile EFH or MFH, `fheat_nrw.processing._add_custom_heat_demand`;
- buildings added from ALKIS where WBM-NRW has none, `fheat_nrw.building_gaps`;
- buildings added by hand, `fheat_de.building_estimate.estimate_building`.

Non-residential buildings take `WVBRpEBF` of `building_functions.json`
instead; they are not affected.

## Source

Loga, Tobias; Stein, Britta (2026): *Tabellenwerte des Typgebäude-Modells zur
energetischen Bewertung des Wohngebäudebestands* (Typgebaeude-Tabellenwerte.xlsx),
correction version v1.2 of 27.04.2026. Institut Wohnen und Umwelt (IWU),
published on Zenodo.

- Record: <https://zenodo.org/records/18166030>, file
  `Typgebaeude-Tabellenwerte_v1.2.xlsx`
- DOI: [10.5281/zenodo.18166030](https://doi.org/10.5281/zenodo.18166030)
  (concept DOI of all versions: 10.5281/zenodo.15488547)
- Licence: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). F|Heat
  changes the values as described below.
- Project: "Repräsentative Typgebäude als Erweiterung der deutschen
  Wohngebäudetypologie" (BBSR, Zukunft Bau, 12.2022–05.2025),
  <https://www.iwu.de/forschung/gebaeudebestand/repraesentative-typgebaeude/>

The workbook models the average German residential building of each size and
age class in the reference year 2025, including the renovations made since
construction. Its values are calculated with the TABULA method and calibrated
to typical consumption.

## Cells used

| What | Sheet | Cells |
|---|---|---|
| Useful heat demand, space heating [kWh/(m²·a) living area] | `Tabellen Anhang B` | column `CM`, rows 57–110 |
| Useful heat demand, hot water [kWh/(m²·a) living area] | `Tabellen Anhang B` | column `CN`, rows 57–110 |
| Living area of the German stock [Mio. m²] | `Tabellen Anhang A` | column `H`, rows 53–106 |

In `Tabellen Anhang B` these rows belong to the block "TABULA-Berechnungsverfahren /
kalibriert auf typisches Verbrauchsniveau" (cell `CF56`), "Differenziertes
Modell 2025". Both sheets list six building variants with nine age classes each:

| Variant | Anhang B rows | Anhang A rows | F\|Heat type |
|---|---|---|---|
| EZFH freistehend (detached) | 57–65 | 53–61 | EFH |
| EZFH Doppelhaushälfte (semi-detached) | 66–74 | 62–70 | EFH |
| EZFH Reihenhaus (und sonstige) (terraced) | 75–83 | 71–79 | EFH |
| MFH mit 3 bis 6 Wohnungen | 84–92 | 80–88 | MFH |
| MFH mit 7 bis 20 Wohnungen | 93–101 | 89–97 | MFH |
| MFH mit 21 oder mehr Wohnungen | 102–110 | 98–106 | MFH |

Age classes in each block: bis 1918, 1919–1948, 1949–1978, 1979–1994,
1995–2001, 2002–2009, 2010–2015, 2016–2020, 2021–2025.

## Derivation

1. **Heating + hot water.** Per variant and IWU age class: `CM + CN`. F|Heat
   uses one demand for space heating and hot water, like `RW_WW` of WBM-NRW.
2. **EFH and MFH.** F|Heat knows only EFH and MFH. The three EFH variants and
   the three MFH variants are averaged, weighted by their living area in the
   stock (`Tabellen Anhang A`, column `H`), so the value stands for the
   average m² of that type and age class.
3. **F|Heat age classes.** Each F|Heat class takes the IWU class of its years
   (the year labels `baujahre` in the JSON are not changed). Where one F|Heat
   class spans two IWU classes, both are averaged, again weighted by living area:

   | F\|Heat class | `baujahre` | IWU class(es) |
   |---|---|---|
   | A, B | vor 1918 | bis 1918 |
   | C | 1918–1948 | 1919–1948 |
   | D, E, F | 1949–1957, 1958–1968, 1969–1978 | 1949–1978 |
   | G, H | 1979–1987, 1988–1993 | 1979–1994 |
   | I | 1994–2001 | 1995–2001 |
   | J | 2002–2010 | 2002–2009 |
   | K | 2011–2016 | 2010–2015 |
   | L | ab 2016 | 2016–2020 and 2021–2025 |

   The IWU model has no finer classes between 1949 and 1994, so D–F and G–H
   share a value. The single years 1918, 1994, 2010 and 2016 fall into the
   neighbouring IWU class.
4. **Rounding** to one decimal.
5. **No area conversion.** The IWU values are per m² living area. F|Heat
   multiplies by the floor area of WBM-NRW, which LANUV defines as footprint ×
   storeys × 0.7 for residential buildings ("Kurzdokumentation
   Raumwärmebedarfsmodell NRW", version 2, 17.12.2024, step 6), and computes
   its own estimates the same way (`NET_FLOOR_FACTOR`). This floor area is
   taken as living area, factor 1.0. The TABULA reference area of the
   workbook is 1.1 × living area; if WBM-NRW's floor area is closer to that,
   F|Heat overestimates by up to about 10 %.

## Result

| Class | EFH | MFH |
|---|---|---|
| A, B | 162.4 | 137.2 |
| C | 162.0 | 138.5 |
| D, E, F | 151.0 | 124.7 |
| G, H | 137.4 | 126.5 |
| I | 111.4 | 106.8 |
| J | 93.8 | 88.6 |
| K | 76.4 | 70.7 |
| L | 72.6 | 66.8 |

## Repeat or check

```bash
pip install -e ".[excel]"
python scripts/derive_age_classes.py Typgebaeude-Tabellenwerte_v1.2.xlsx          # compare, exit 1 if different
python scripts/derive_age_classes.py Typgebaeude-Tabellenwerte_v1.2.xlsx --write  # write into the JSON
```

The script checks the block label and every variant and age class label before
it reads a value, so a different layout of a later version stops it instead
of reading wrong cells.

## Previous values

Until this change the table held the ARGE values, whose source the repository
does not document (EFH 188.2, MFH 155.0 for the oldest class; MFH 40.9 for L). With the new values the
heat demand of the Burgsteinfurt test example (`tests/test_xwp_golden.py`)
falls by about 10 %.
