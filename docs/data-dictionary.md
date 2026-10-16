# Data dictionary

What every stored field means, its unit, and the rules the import holds it
to. The diagrams live in [conception](conception.md).

## Source

CEPII BACI, HS 2012 nomenclature, release V202601, years 2012 to 2024. One
CSV per year inside `BACI_HS12_V202601.zip`, plus a country and a product
dictionary. BACI reconciles what exporters and importers declare to UN
Comtrade into one value per flow.

| BACI column | Meaning | Stored as |
| --- | --- | --- |
| `t` | year | `year`, int |
| `i` | exporter, BACI country code | `countryCode`, int |
| `j` | importer, BACI country code | only 788 (Tunisia) is kept as a supplier flow |
| `k` | product, HS12 six digits | `productCode`, text with leading zeros |
| `v` | value, thousand current USD | `valueUsd` = `v` × 1000, Decimal128 |
| `q` | quantity, metric tonnes | `quantityTonnes`, Decimal128 or null |

Cite as Gaulier, G. and Zignago, S. (2010). BACI: International Trade
Database at the Product-Level. The 1994-2007 Version. CEPII Working Paper,
N°2010-23. The data is published under the Etalab Open License 2.0.

## Import rules

1. A snapshot becomes `ready` only after all 13 annual files are read. A
   missing file marks it `failed` with the reason.
2. Importing the same archive twice changes nothing. Importing a different
   archive under the same release name is refused.
3. Product codes stay text, so `010121` keeps its zero.
4. Values are exact decimals from the CSV text. No float touches them before
   the API response.
5. A blank or `NA` quantity stays null. It is never zero.
6. Rows go to the snapshot's error report, never into the data, when they
   are malformed, have a non-positive value, a year that does not match the
   file, or a country or product code missing from the dictionaries.
7. Two rows for the same Tunisian product and exporter in one year are
   ambiguous, so both go to the error report.
8. World exporter totals add every accepted row except Tunisia's own
   exports, whoever the importer is.

## Metrics

All shares and indexes are fractions from 0 to 1.

| Field | Definition |
| --- | --- |
| `totalUsd` | sum of supplier values |
| `supplierCount` | suppliers with a positive value |
| `topSupplier.share` | largest supplier value ÷ total |
| `top3Share` | three largest supplier values ÷ total |
| `hhi` | Σ share², unnormalised. 1 means one supplier, 1/n means n equal suppliers |
| `world.hhi` | the same index over world exporters of the product |

An HHI of 0.25 or more is read as highly concentrated, the line the 2010 US
Horizontal Merger Guidelines draw at 2500 on the 0 to 10000 scale.

A chapter (2 digits) or heading (4 digits) sums each supplier's value across
its products first, then computes shares and HHI on the sums. Averaging
product HHIs would let a tiny product count as much as a large one. Tonnes
are never summed across products.

## Scenario

For a reduction `r` between 0 and 1 and a set of selected suppliers:

| Field | Definition |
| --- | --- |
| `affectedUsd` | r × Σ value of the selected suppliers |
| `exposureShare` | `affectedUsd` ÷ baseline total |
| `remainingUsd` | baseline total − `affectedUsd` |
| `remaining.hhi` | HHI after cutting the selected suppliers by r |

Unselected suppliers keep their value. The model assumes no replacement and
no price response, so `affectedUsd` is historical import value exposed under
the scenario, not a forecast of losses. Country mode runs the same
calculation on every product Tunisia imported in the year and reports the
sum.

## Reports

A report stores its specification, the snapshot id with the archive's
SHA-256, the calculation version, the limitations and the full result. It is
never recomputed, so a later release or a code change leaves it as saved.
