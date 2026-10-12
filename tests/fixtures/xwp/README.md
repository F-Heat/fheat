# Testdaten XWärmeplan

Auszüge aus den Referenzplänen der XLeitstelle, https://gitlab.opencode.de/xleitstelle/xwaermeplan/implementierung, Ordner `Referenzplaene`, Commit `52b9e3e624ffa1ee88b3a4abc8fb130fe1250fb4` (06.10.2026). Die Pläne sind abgeschlossene kommunale Wärmeplanungen (Aachen, Oberhausen, Rheinberg), die die XLeitstelle in XWärmeplan 0.9.6 überführt hat.

Erzeugt mit `scripts/excerpt_xwp_reference.py` (Standardwerte: je Objektart fünf Fachobjekte mit höchstens 400 Koordinaten, alle Objekte ohne Raumbezug):

| Datei | Original |
|---|---|
| `rheinberg_xmas_auszug.gml` / `.json` | `Rheinberg_v096_xmas.gml` / `.json` |
| `rheinberg_ldproxy_auszug.gml` | `Rheinberg_v096_ldproxy.gml` |
| `oberhausen_xmas_auszug.gml` / `.json` | `Oberhausen_v096_xmas.gml` / `.json` |
| `aachen_xmas_auszug.gml` / `.json` | `Aachen_v096_xmas.gml` / `.json` |

Die GML-Auszüge sind gegen die XSD gültig. Die JSON-Auszüge folgen wie die Originale nicht dem offiziellen JSON-Schema (siehe `docs/xwaermeplan/abgleich.md`, J1) und dienen nur als Lesetest.

Das Repo `implementierung` enthält keine Lizenzdatei; Nutzungsbedingungen sind bei der XLeitstelle zu klären.
