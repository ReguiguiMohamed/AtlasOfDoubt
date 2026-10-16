# atlas

The Python package and the web app it serves. `python -m atlas.ingest` loads
a BACI release into MongoDB, and `uvicorn atlas.api:app` serves the API and
the static app from the same process.

| File | Runs on | What it does |
| --- | --- | --- |
| [`metrics.py`](metrics.py) | import and every request | totals, shares, top-3 share, HHI, group merging and the disruption scenario |
| [`db.py`](db.py) | both | connects with Decimal stored as Decimal128 and creates the indexes |
| [`ingest.py`](ingest.py) | once per release | streams the 13 annual files, keeps flows into Tunisia, computes world exporter totals, writes the error report |
| [`routes.py`](routes.py) | every request | the modelled sea lane from each supplier country to Tunis and the chokepoints on it |
| [`api.py`](api.py) | server | read endpoints, scenario preview, immutable reports, CSV export, the static mount |
| [`static/`](static/) | browser | plain ES modules with a hash router, ECharts 5.6.0 and Tabulator 6.3.1 from jsDelivr with SRI hashes |

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB server |
| `ATLAS_DB` | `atlas` | database name. The tests use `atlas_test` and drop it before each test |

## One set of numbers

Only `metrics.py` does arithmetic. The import uses it to store each
product-year's measures, the API uses it for history, groups and scenarios,
and so a preview and the report saved from it come from the same function
on the same stored values. The sea routes view sums supplier values per
route with `metrics.total` and `metrics.with_shares` too. Reports carry
`CALCULATION_VERSION`. Old ones show it.

Values stay `Decimal` from the CSV text to the API boundary. FastAPI turns
them into JSON numbers there, and the CSV export writes them as exact
decimal text.

## Snapshots

The snapshot id is the archive name without `.zip`, for example
`BACI_HS12_V202601`. Every request names one, so a new release imported
next to an old one changes nothing for readers of the old one. Reports copy
the snapshot's source and archive hash at save time.

## Web app

| Route | View |
| --- | --- |
| `#/overview?year&minValue` | every product of a year with its concentration, the "Choice or structure?" quadrant of Tunisian against world HHI and the products whose HHI rose or fell the most since an earlier year |
| `#/country` and `#/country/{code}?year` | every supplier country with a search box, then one country: its modelled sea route, what it sent each year, the products it supplies and its rank among their suppliers |
| `#/routes?year&code&select` | supplier value summed per sea route and per chokepoint on a map, for all products or one code, with a detail panel for the selected route or strait: trend, countries, the products most exposed and a link to simulate its closure |
| `#/product/{code}?year` | one product, heading or chapter: supplier bars and table, imports and HHI from 2012 to 2024, supplier shares over time, for one product the largest world exporters against what each sent Tunisia, and a link to its sea routes |
| `#/scenario?mode&code&year&suppliers&reduction` | product or supplier-country disruption, previewed live, saved as a report |
| `#/reports` and `#/reports/{id}` | saved reports with provenance, limitations, CSV download and a print layout that keeps every table row |

Each view renders into a fresh section, so a slow request from a view the
reader already left writes into a detached node instead of the current page.

## Sea routes

BACI records who sold what, not how it travelled. [`routes.py`](routes.py)
gives each supplier country one usual lane to Tunis, so the value behind
Suez or Hormuz is an estimate of exposure, not a shipping record. Countries
around the Mediterranean and overland neighbours pass no chokepoint. A
country no route lists is counted as unrouted, and a test fails if any route
names an unknown chokepoint or lists a country twice.

## Tests

`pytest -q` runs 53 tests in about 10 seconds against a local MongoDB on port
27017. CI starts a MongoDB 9.0 service for them.

| Guarantee | Tests |
| --- | --- |
| The blueprint example gives top share 60%, top 3 100%, HHI 0.46 | `test_metrics.py::test_blueprint_example` |
| Affected value is r × Σ selected, other suppliers unchanged | `test_api.py::test_product_scenario_follows_the_blueprint_rule` |
| Groups compute shares from summed values | `test_metrics.py::test_group_recomputes_shares_from_summed_values`, `test_api.py::test_history_of_a_group_sums_suppliers_before_shares` |
| Tonnes are never added across products | `test_api.py::test_country_scenario_ranks_products_and_never_adds_tonnes` |
| Codes keep leading zeros, values convert exactly, missing tonnes stay null | `test_ingest.py::test_leading_zeros_survive`, `::test_values_are_converted_from_thousands_of_usd_exactly`, `::test_missing_quantity_stays_missing` |
| Bad rows go to the error report | `test_ingest.py::test_untrusted_rows_go_to_the_error_report` |
| Re-import is idempotent, a missing year fails the snapshot | `test_ingest.py::test_importing_twice_creates_no_duplicates`, `::test_missing_year_fails_the_snapshot` |
| Shifts count only products over the minimum value in both years | `test_api.py::test_movers_need_the_minimum_value_in_both_years` |
| Reports ignore browser numbers and survive a new snapshot | `test_api.py::test_report_ignores_numbers_sent_by_the_browser`, `::test_report_is_unchanged_after_another_snapshot_is_added` |
| Route and chokepoint totals are sums of their countries | `test_api.py::test_routes_sum_countries_into_routes_and_chokepoints`, `::test_routes_of_one_product` |
