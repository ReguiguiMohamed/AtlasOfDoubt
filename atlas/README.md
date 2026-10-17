# atlas

The Python package and the web app it serves. `python -m atlas.prepare`
turns a BACI release into a snapshot any country can be read from, and
`uvicorn atlas.api:app` serves the API and the static app from the same
process.

| File | Runs on | What it does |
| --- | --- | --- |
| [`metrics.py`](metrics.py) | preparation and every request | totals, shares, top-3 share, HHI, group merging, RCA, unit values and their quality flags, PRODY, EXPY and the disruption scenario |
| [`db.py`](db.py) | both | connects with Decimal stored as Decimal128 and creates the indexes |
| [`prepare.py`](prepare.py) | once per release | checks the 13 annual files in DuckDB, writes flows as Parquet by importer and year, stores world and country-year aggregates, writes the error report |
| [`materialize.py`](materialize.py) | first visit to a country | builds that country's import and export view from its Parquet partition into MongoDB, under a lease, and evicts the least recently used views |
| [`routes.py`](routes.py) | every request | the modelled sea lane from each partner region to the reporter and the chokepoints on it |
| [`api.py`](api.py) | server | read endpoints scoped by `snapshot` and `reporter`, scenario preview, immutable reports, CSV export, the static mount |
| [`static/`](static/) | browser | plain ES modules with a hash router, ECharts 5.6.0 and Tabulator 6.3.1 from jsDelivr with SRI hashes |

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB server |
| `ATLAS_DB` | `atlas` | database name. The tests use `atlas_test` and drop it before each test |
| `ATLAS_DATA` | `data/snapshots` | where prepared Parquet snapshots live |

## Adding a release

```bash
python -m atlas.prepare data/raw/BACI_HS12_V202701.zip
```

That is the whole step. GDP per capita comes from the World Bank file in
`data/snapshots/wdi-gdp.json`, downloaded on the first run and reused after,
or from a path given as a second argument. The snapshot id is the archive
name plus a hash of every input, for example `BACI_HS12_V202601@eadf14964b1c`.
Work happens in a
`.partial` folder that is renamed only when every year is written, so an
interrupted run leaves nothing a reader can pick. Running it again with the
same files returns the existing snapshot. A new GDP file or a change to the
formulas gives a new id beside the old one. Every request names its
snapshot, so readers of an older one see no change, and reports copy the
snapshot's source and archive hash at save time.

## One set of numbers

Only `metrics.py` does arithmetic. Preparation uses it for world totals and
PRODY, the country build for each product-year's measures, the API for
history, groups and scenarios, and so a preview and the report saved from
it come from the same function on the same stored values. Reports carry
`CALCULATION_VERSION`. Old ones show it.

Values stay `Decimal` from the CSV text to the API boundary. FastAPI turns
them into JSON numbers there, and the CSV export writes them as exact
decimal text.

## Country views

A country's documents are built on its first visit and tagged with one
generation id. Readers see a generation only after its job is marked ready,
so a build that fails halfway shows nothing. A second request during a build
waits for it, and a build whose 10 minute lease ran out is taken over. Past
1 GB the least recently used generations are dropped and rebuilt on the next
visit.

## Web app

The header picks the reporting country, stored in `?reporter=` so a shared
link opens on the same one. Without it the app asks for a country first.

| Route | View |
| --- | --- |
| `#/overview?year&minValue` | every product the reporter imported in a year with its concentration, the "Choice or structure?" quadrant of its HHI against the world's and the products whose HHI rose or fell the most since an earlier year |
| `#/exports?year&minValue` | exports and imports from 2012 to 2024, product and destination HHI, EXPY when GDP was prepared, destinations, and each product with its world share, RCA, unit value and quality flags |
| `#/country` and `#/country/{code}?year` | every partner country with a search box, then one partner: its modelled sea route, what it supplied and bought back each year, the products it supplies and its rank among their suppliers |
| `#/routes?year&code&select` | supplier value summed per sea route and per chokepoint on a map, for all products or one code, with a detail panel for the selected route or strait: trend, countries, the products most exposed and a link to simulate its closure |
| `#/product/{code}?year` | one product, heading or chapter: supplier bars and table, imports, exports, RCA and HHI from 2012 to 2024, supplier shares over time, for one product the largest world exporters against what each sent the reporter, and a link to its sea routes |
| `#/scenario?mode&code&year&suppliers&reduction` | product or supplier-country disruption, previewed live, saved as a report |
| `#/reports` and `#/reports/{id}` | the reporter's saved reports with provenance, limitations, CSV download and a print layout that keeps every table row |

Both maps zoom with the wheel, a pinch or the + and − buttons, and pan by dragging. Whole world resets them.

Every other chart zooms with Ctrl and the wheel or a box drawn after its zoom
button, pans with a mouse drag and resets on a double-click. A plain wheel or
a finger still scrolls the page. Bar charts zoom along their categories only.
Scatter charts zoom both axes, which spreads a crowd of dots apart. The same
toolbar saves the chart as a PNG.

Each view renders into a fresh section, so a slow request from a view the
reader already left writes into a detached node instead of the current page.

## Sea routes

BACI records who sold what, not how it travelled. [`routes.py`](routes.py)
puts each country in one sea region with a hub port and joins the regions
by usual lanes, so a partner's route is the shortest path from its hub to
the reporter's. The value behind Suez or Hormuz is an estimate of exposure,
not a shipping record. Partners in the reporter's own region pass no
chokepoint. A country no region lists is counted as unrouted, and a test
fails if a country sits in two regions or a route does not end at the
reporter.

## Tests

`pytest -q` runs 69 tests against a local MongoDB on port 27017. CI starts a
MongoDB 9.0 service for them.

| Guarantee | Tests |
| --- | --- |
| The blueprint example gives top share 60%, top 3 100%, HHI 0.46 | `test_metrics.py::test_blueprint_example` |
| Affected value is r × Σ selected, other suppliers unchanged | `test_api.py::test_product_scenario_follows_the_blueprint_rule` |
| Groups compute shares from summed values | `test_metrics.py::test_group_recomputes_shares_from_summed_values`, `test_api.py::test_history_of_a_group_sums_suppliers_before_shares` |
| Tonnes are never added across products | `test_api.py::test_country_scenario_ranks_products_and_never_adds_tonnes` |
| Codes keep leading zeros, values convert exactly, missing tonnes stay null | `test_prepare.py::test_leading_zeros_survive`, `::test_values_are_converted_from_thousands_of_usd_exactly`, `::test_missing_quantity_stays_missing` |
| Bad rows go to the error report with their line | `test_prepare.py::test_untrusted_rows_go_to_the_error_report`, `::test_each_broken_row_is_named_with_its_line` |
| Preparing twice is idempotent, a missing year fails the snapshot | `test_prepare.py::test_preparing_twice_creates_no_duplicates`, `::test_missing_year_fails_the_snapshot` |
| The world comparison leaves the reporter out | `test_prepare.py::test_metrics_and_world_comparison_leave_the_reporter_out` |
| RCA, unit values, PRODY and EXPY | `test_prepare.py::test_exports_carry_rca_unit_value_and_coverage`, `::test_prody_and_expy_use_same_year_income` |
| One reporter never sees another's flows | `test_api.py::test_each_reporter_sees_only_its_own_flows_whatever_the_visit_order` |
| Country views survive eviction, failure and an expired lease | `test_api.py::test_an_evicted_view_is_rebuilt_with_the_same_figures`, `::test_a_failed_build_leaves_nothing_readable`, `::test_a_build_whose_lease_expired_is_taken_over` |
| Shifts count only products over the minimum value in both years | `test_api.py::test_movers_need_the_minimum_value_in_both_years` |
| Reports ignore browser numbers and survive a new snapshot | `test_api.py::test_report_ignores_numbers_sent_by_the_browser`, `::test_report_is_unchanged_after_another_snapshot_is_added` |
| Route and chokepoint totals are sums of their countries, and routes follow the reporter | `test_api.py::test_routes_sum_countries_into_routes_and_chokepoints`, `::test_routes_follow_the_reporter`, `::test_the_route_depends_on_the_reporter` |
