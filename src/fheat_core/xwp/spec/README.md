# XWärmeplan-Spezifikation (vendort)

Kopien der Schemas für die Offline-Validierung. Nicht von Hand ändern; neu erzeugen mit

```
python scripts/fetch_xwp_spec.py --version 0.9.6 --spec-repo <Klon von xleitstelle/xwaermeplan/spezifikation>
```

## Herkunft

| Ordner | Quelle | Stand |
|---|---|---|
| `0.9.6/xsd/waermeplan.xsd`, `0.9.6/json/featurecollection.json`, `0.9.6/json/features.json` | XLeitstelle, https://gitlab.opencode.de/xleitstelle/xwaermeplan/spezifikation | Commit `2f7715e70c35042f9e5c13c2157ddd9a02ef704c` (08.09.2026) |
| `0.9.6/xsd/schemas.opengis.net/gml/3.2.1/`, `…/iso/19139/`, `…/ogcapi/features/`, `…/gmlsfProfile/` | Open Geospatial Consortium, http://schemas.opengis.net | abgerufen 12.10.2026 |
| `0.9.6/xsd/www.w3.org/` | W3C, http://www.w3.org/1999/xlink.xsd und http://www.w3.org/2001/xml.xsd | abgerufen 12.10.2026 |
| `0.9.6/json/json-fg/` (außer `link.json`) | OGC, https://github.com/opengeospatial/ogc-feat-geo-json, Tag `v0.2.2`, `core/schemas/` | JSON-FG 0.2.2 |
| `0.9.6/json/json-fg/link.json` | OGC, https://beta.schemas.opengis.net/json-fg/link.json (informatives Schema) | abgerufen 12.10.2026 |

Zeilenenden wurden auf LF vereinheitlicht, sonst sind die Dateien unverändert.

## Lizenz

- **OGC-Schemas:** OGC Document/Software Notice, https://www.ogc.org/about/policies/ ; Weitergabe mit Herkunftsangabe erlaubt.
- **W3C `xml.xsd`, `xlink.xsd`:** W3C Software and Document License.
- **XWärmeplan (XLeitstelle):** Das Repo `spezifikation` enthält keine Lizenzdatei. Die Dateien werden hier nur zur Validierung mitgeliefert; die Nutzungsbedingungen sind bei der XLeitstelle zu klären (siehe `docs/xwaermeplan/abgleich.md`, Abschnitt 5).
