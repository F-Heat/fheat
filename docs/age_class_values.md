# Specific heat demand of the age classes

Where the EFH and MFH values in
[`src/fheat_de/data/building_age_classes.json`](../src/fheat_de/data/building_age_classes.json)
(`waerme_efh_kwh_m2a`, `waerme_mfh_kwh_m2a`, and the LANUV factors
`faktor_lanuv_efh`, `faktor_lanuv_mfh`) come from and how they were derived.
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

## What the value means

The values are the **final energy of a building supplied by district heating**
for space heating and hot water, calculated with the **standard boundary
conditions** of the TABULA method:

- **District heating:** the heat delivered at the building's substation, which
  the heat network has to supply: the useful heat plus the losses inside the
  building (substation, distribution, hot water storage and circulation),
  without the losses of a boiler. "Bezogen auf Brennwert" in the column title
  only matters for fuels; for district heating the final energy is the
  delivered heat.
- **Standard boundary conditions, not calibrated:** the whole building heated
  to the standard indoor temperature, standard climate and standard hot water
  demand. The workbook also gives values calibrated to typical consumption;
  their calibration factors (0.77 to 1.04) show that the standard calculation
  is about 20–30 % above the typical consumption of old buildings, and close
  to it for buildings from 2002 on.

LANUV's `RW_WW` of WBM-NRW is useful heat ("Raumwärmebedarf (Nutzenergie)"
plus hot water). So that `heat_demand_basis="dataset"` means final energy as
well, the NRW adapter multiplies it by a factor, see
[Factor for the LANUV data](#factor-for-the-lanuv-data).

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
construction, with the TABULA method.

## Cells used

| What | Sheet | Cells |
|---|---|---|
| Final energy district heating, heating + hot water [kWh/(m²·a) living area] | `Tabellen Anhang C` | column `AH`, rows 21–74 |
| Living area of the German stock [Mio. m²] | `Tabellen Anhang A` | column `H`, rows 53–106 |
| Useful heat, heating and hot water [kWh/(m²·a) living area] (only for the LANUV factor) | `Tabellen Anhang C` | columns `L` and `M`, rows 21–74 |

In `Tabellen Anhang C` column `AH` belongs to the block "(Teil-)Energiekennwerte
für monovalente Zentralheizsysteme – Niedertemperaturkessel / Heizöl und
Fernwärme, TABULA-Berechnung mit Standardrandbedingungen" (cell `W5`), supply
system "Fernwärme" (cell `AF8`), column "Heizung + Warmwasser" of
"Endenergiebedarf" (cell `AH10`), rows of the "Differenziertes Modell 2025".
The auxiliary energy (column `AI`, electricity) is not included. Columns `L`
("Heizung") and `M` ("Warmwasser") of "Nutzwärmebedarf" (cells `L10`, `M10`)
belong to the block "… – Brennwert-Kessel / Erdgas, TABULA-Berechnung mit
Standardrandbedingungen" (cell `E5`); the useful heat is the same for every
supply system. Both sheets
list six building variants with nine age classes each:

| Variant | Anhang C rows | Anhang A rows | F\|Heat type |
|---|---|---|---|
| EZFH freistehend (detached) | 21–29 | 53–61 | EFH |
| EZFH Doppelhaushälfte (semi-detached) | 30–38 | 62–70 | EFH |
| EZFH Reihenhaus (und sonstige) (terraced) | 39–47 | 71–79 | EFH |
| MFH mit 3 bis 6 Wohnungen | 48–56 | 80–88 | MFH |
| MFH mit 7 bis 20 Wohnungen | 57–65 | 89–97 | MFH |
| MFH mit 21 oder mehr Wohnungen | 66–74 | 98–106 | MFH |

Age classes in each block: bis 1918, 1919–1948, 1949–1978, 1979–1994,
1995–2001, 2002–2009, 2010–2015, 2016–2020, 2021–2025.

## Derivation

1. **Heating + hot water.** Column `AH` per variant and IWU age class, the sum
   the workbook gives. F|Heat uses one demand for space heating and hot water.
2. **EFH and MFH.** F|Heat knows only EFH and MFH. The three EFH variants and
   the three MFH variants are averaged, weighted by their living area in the
   stock (`Tabellen Anhang A`, column `H`), so the value stands for the
   average m² of that type and age class.
3. **F|Heat age classes.** The F|Heat classes are those of the IWU residential
   building typology (Loga et al. 2015, *Deutsche Wohngebäudetypologie*), with
   its letters and years; the edges follow the German thermal insulation and
   energy saving ordinances (WSchVO 1977, 1984, 1995, EnEV 2002, 2009, 2016).
   The type building model of 2025 merges some of them, so each F|Heat class
   takes the model class that contains its years. L spans two model classes;
   both are averaged, again weighted by living area:

   | F\|Heat class | `baujahre` | Model class(es) 2025 |
   |---|---|---|
   | A, B | bis 1918 | bis 1918 |
   | C | 1919–1948 | 1919–1948 |
   | D, E, F | 1949–1957, 1958–1968, 1969–1978 | 1949–1978 |
   | G, H | 1979–1983, 1984–1994 | 1979–1994 |
   | I | 1995–2001 | 1995–2001 |
   | J | 2002–2009 | 2002–2009 |
   | K | 2010–2015 | 2010–2015 |
   | L | ab 2016 | 2016–2020 and 2021–2025 |

   D–F and G–H share a value. A is kept as a copy of B: the typology's A
   (until 1859) has no class of its own in the model, and the NRW adapter
   never assigns it. The NRW adapter assigns the classes by the year of the
   parcel record with the same edges (`BAK_BINS` in `fheat_nrw/processing.py`).
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

Specific heat demand in kWh/(m²·a); "old" are the previous (ARGE) values,
see [Previous values](#previous-values). The old year ranges differed
slightly (e.g. G 1979–1987, H 1988–1993).

| Class | EFH old | EFH | MFH old | MFH |
|---|---|---|---|---|
| A, B | 188.2 | 233.0 | 155.0 | 169.7 |
| C | 199.0 | 230.3 | 159.0 | 171.3 |
| D | 202.0 | 208.1 | 156.8 | 150.7 |
| E | 196.6 | 208.1 | 154.4 | 150.7 |
| F | 185.5 | 208.1 | 147.9 | 150.7 |
| G | 155.7 | 183.9 | 129.6 | 153.4 |
| H | 144.0 | 183.9 | 122.5 | 153.4 |
| I | 114.5 | 144.4 | 115.3 | 126.8 |
| J | 91.4 | 119.1 | 96.1 | 104.2 |
| K | 81.5 | 99.7 | 74.1 | 84.7 |
| L | 70.1 | 94.2 | 40.9 | 79.6 |

## Example: EFH, class A/B (bis 1918)

1. Heating + hot water per variant (`Tabellen Anhang C`, `AH`, rows 21, 30, 39):

   | Variant | Heating + hot water | Living area of the stock (`Tabellen Anhang A`, `H`) |
   |---|---|---|
   | EZFH freistehend | 244.0 | 188.8 Mio. m² |
   | EZFH Doppelhaushälfte | 219.0 | 25.3 Mio. m² |
   | EZFH Reihenhaus | 205.4 | 62.1 Mio. m² |

2. Weighted by living area:
   (244.0 × 188.8 + 219.0 × 25.3 + 205.4 × 62.1) / (188.8 + 25.3 + 62.1)
   = 64,363 / 276.2 = **233.0 kWh/(m²·a)**, the value of A and B for EFH.
   276.2 Mio. m² is the living area of all EFH up to 1918. (The cells hold more
   decimals; the script uses them and also gets 233.0.)

3. For a building of this class with 100 m² footprint and 2 storeys:
   floor area 0.7 × 100 × 2 = 140 m², heat demand 140 × 233.0 = 32,620 kWh/a,
   thermal power 32,620 / 1,600 full load hours (Wohnhaus) = 20.4 kW.

## Factor for the LANUV data

LANUV's `RW_WW` is useful heat, the values above are final energy with
district heating. With `heat_demand_basis="dataset"` the NRW adapter
multiplies `RW_WW` of every building with load profile EFH or MFH by the
factor of its age class and type (`fheat_nrw.processing._lanuv_factor`), so
both bases mean the heat the network delivers. This also applies to
buildings added from ALKIS, whose demand comes from LANUV's specific demand
(`fheat_nrw.building_gaps`). Non-residential buildings, buildings without an
age class and an own `building_age_classes.json` without the factors keep
the LANUV value.

1. Per variant and IWU class: final energy district heating (`AH`) ÷ useful
   heat (`L` + `M`), both with standard boundary conditions.
2. The plain mean of the three EFH and of the three MFH variants, **not**
   weighted by living area (the method agreed in the project; weighting would
   give 0.002–0.013 lower factors). L takes the plain mean of the six values
   of 2016–2020 and 2021–2025.
3. Rounding to three decimals.

| Class | EFH | MFH |
|---|---|---|
| A, B | 1.137 | 1.116 |
| C | 1.140 | 1.118 |
| D, E, F | 1.154 | 1.130 |
| G, H | 1.172 | 1.126 |
| I | 1.220 | 1.153 |
| J | 1.271 | 1.186 |
| K | 1.334 | 1.229 |
| L | 1.360 | 1.244 |

The factor grows for newer buildings: their useful heat is small, while the
losses in the building (distribution, storage, circulation) stay similar.

Example EFH, class A/B: 244.0 / 216.9 = 1.125 (freistehend),
219.0 / 192.4 = 1.138 (Doppelhaushälfte), 205.4 / 179.0 = 1.147 (Reihenhaus);
mean (1.125 + 1.138 + 1.147) / 3 = **1.137**. A building with `RW_WW`
= 30,000 kWh/a gets 34,110 kWh/a.

## Repeat or check

```bash
pip install -e ".[excel]"
python scripts/derive_age_classes.py Typgebaeude-Tabellenwerte_v1.2.xlsx          # compare, exit 1 if different
python scripts/derive_age_classes.py Typgebaeude-Tabellenwerte_v1.2.xlsx --write  # write into the JSON
```

The script checks the block, supply system and column titles and every
variant and age class label before it reads a value, so a different layout
of a later version stops it instead of reading wrong cells.

## Previous values

Until this change the table held the ARGE values, whose source the repository
does not document (EFH 188.2, MFH 155.0 for the oldest class; MFH 40.9 for L),
with year ranges that differed from the IWU classes at 1918, 1984–1994 and
from 2002 on.
