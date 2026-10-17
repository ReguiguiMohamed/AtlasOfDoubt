# Data dictionary

What every stored field means, its unit, and the rules preparation holds it
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
| `j` | importer, BACI country code | the Parquet partition, and the reporter whose imports a flow is |
| `k` | product, HS12 six digits | `productCode`, text with leading zeros |
| `v` | value, thousand current USD | `valueUsd` = `v` × 1000, Decimal128 |
| `q` | quantity, metric tonnes | `quantityTonnes`, Decimal128 or null |

Cite as Gaulier, G. and Zignago, S. (2010). BACI: International Trade
Database at the Product-Level. The 1994-2007 Version. CEPII Working Paper,
N°2010-23. The data is published under the Etalab Open License 2.0.

## Preparation rules

1. A snapshot becomes `ready` only after all 13 annual files are written and
   read back. A missing file marks it `failed` with the reason.
2. Preparing the same files twice changes nothing. A different archive or
   GDP file under the same release name gets its own snapshot id.
3. Product codes stay text, so `010121` keeps its zero.
4. Values are exact decimals from the CSV text. No float touches them before
   the API response.
5. A blank or `NA` quantity stays null. It is never zero.
6. Rows go to the snapshot's error report, never into the data, when they
   are malformed, have a non-positive value, a year that does not match the
   file, or a country or product code missing from the dictionaries.
7. Two rows for the same importer, product and exporter in one year are
   ambiguous, so every one of them goes to the error report.
8. A reporter's world comparison adds every accepted row except the
   reporter's own exports, whoever the importer is.

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

## Export measures

Read from the reporter's exports in one year, all values in current USD.

| Field | Definition |
| --- | --- |
| `exportsUsd` | sum of the reporter's exports to every destination |
| `productHhi` | HHI over the reporter's export value per product |
| `geoHhi` | HHI over the reporter's export value per destination |
| `worldShare` | the reporter's exports of a product ÷ world exports of it |
| `rca` | Balassa revealed comparative advantage, (X_ck ÷ X_c) ÷ (X_k ÷ X). Above 1, the reporter exports relatively more of the product than the world does |
| `unitValueUsdPerTonne` | value ÷ tonnes, over the flows that report a positive quantity |
| `quantityCoverage` | value with a quantity ÷ total value |
| `prody` | income of the countries exporting a product, each weighted by the product's share in its own basket relative to the other exporters. GDP per capita, PPP, constant international dollars, same year |
| `expy` | Σ basket share × PRODY. Null when any product in the basket lacks a PRODY, with `coverage` and `coveredBasket` beside it |
| `expyFixed2012` | EXPY with the 2012 PRODY of the countries that have income in every year, so it moves only when the basket changes |

A unit value carries quality flags and is read as a price only when none is
raised: `partial quantities` below 50% coverage, `tiny quantity` under one
tonne, and `extreme unit value` outside 0.1 to 10 times the world unit value
of the product.

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
calculation on every product the reporter imported in the year and reports
the sum.

## Reports

A report stores its specification, the snapshot id with the archive's
SHA-256, the calculation version, the limitations and the full result. It is
never recomputed, so a later release or a code change leaves it as saved.
