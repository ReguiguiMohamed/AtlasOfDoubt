# atlas

The Python package and the web app it serves. `python -m atlas.prepare`
turns a BACI release into a snapshot any country can be read from, and
`uvicorn atlas.api:app` serves the API and the static app from the same
process.

| File | Runs on | What it does |
| --- | --- | --- |
| [`metrics.py`](metrics.py) | preparation and every request | totals, shares, top-3 share, HHI, group merging, RCA, unit values and their quality flags, PRODY, EXPY and the disruption scenario |
| [`db.py`](db.py) | both | connects with Decimal stored as Decimal128 and creates the indexes |
| [`prepare.py`](prepare.py) | once per release | checks the 13 annual files in DuckDB, writes flows as Parquet by importer and year, stores world and country-year aggregates, the CEPII GeoDist pairs, the tariffs and the HS section, chapter and heading names of each product, builds the trade graph and the trade-twin vectors, writes the error report |
| [`graph.py`](graph.py) | preparation and the product page | writes the last year's trade as a Ladybug graph, one edge per exporter, importer and HS4 heading, and answers the supplier-network questions with Cypher |
| [`twins.py`](twins.py) | preparation, the imports and exports pages | writes each country's last-year import and export basket to Milvus Lite as a sparse vector of square-rooted HS6 shares, and ranks every country by inner product, the Bhattacharyya coefficient of the two baskets |
| [`coverage.py`](coverage.py) | before adding tariffs or geography | matches the WITS/TRAINS schedule list and CEPII GeoDist to BACI's countries and writes `coverage.csv` with each country's tariff years, HS revision and geography |
| [`tariffs.py`](tariffs.py) | before adding tariffs | downloads each country's latest WITS/TRAINS MFN schedule, the preferential rate of each partner it lists and the WITS HS concordances, maps every schedule to HS2012 and writes `tariffs.csv`, `tariff-schedules.csv`, `preferences.csv` and `tariff-partners.csv` |
| [`materialize.py`](materialize.py) | first visit to a country | builds that country's import and export view from its Parquet partition into MongoDB, with the last year's export destinations of each product, under a lease, and evicts the least recently used views |
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
Tariffs join when `tariffs.csv` and `tariff-schedules.csv` are in
`data/snapshots/`, written by `python -m atlas.coverage` and then
`python -m atlas.tariffs`. A schedule in HS2012 keeps its rates. One in
HS2007 or HS2002 gives each HS2012 code the one older code WITS maps it to.
Where several HS2017 codes meet in one HS2012 code, the row keeps their
lowest and highest rate and how many codes met, and never averages them.
EU members share the EUN schedule, stored once.
Preferences join when `preferences.csv` and `tariff-partners.csv` are there
too. WITS files a preference under a partner country or a beneficiary group,
and the TRAINS beneficiaries file from 2018 names each group's members. A newer
group has no members there, so the snapshot lists it as unresolved and never
applies it. The API gives each market the lower of its MFN rate and the best
preference covering the reporter, and members of one customs union charge
each other nothing.
The last year's flows also go into `graph.lbug` in the snapshot folder, a
Ladybug graph the product page opens read-only, and into `twins.db`, a Milvus
Lite folder with one collection per flow.
Each panel names the store it reads. If either file is missing, the API answers
503 for that panel alone and the page says the store is unavailable.
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
| `#/overview?year&minValue` | every product the reporter imported in a year with its concentration, a donut and ranked list of its imports that drill from HS sections through chapters and headings to products, the "Choice or structure?" quadrant of its HHI against the world's and the products whose HHI rose or fell the most since an earlier year, and the reporter's import twins on a full-width map above bars split by the products they share most |
| `#/exports?year&minValue` | exports and imports from 2012 to 2024, product and destination HHI, EXPY when GDP was prepared, destinations with their distance, border and language, a bubble chart of each destination's value against its distance with the fitted trend, and each product with its world share, RCA, unit value and quality flags, and the reporter's export twins on a map and in bars split by the products they share most |
| `#/country` and `#/country/{code}?year` | every partner country with a search box, then one partner: its distance in km between the most populated cities, a shared border or official language, whether it is landlocked, its modelled sea route, what it supplied and bought back each year, the products it supplies and its rank among their suppliers |
| `#/routes?year&code&select` | supplier value summed per sea route and per chokepoint on a map, for all products or one code, with a detail panel for the selected route or strait: trend, countries, the products most exposed and a link to simulate its closure |
| `#/product/{code}?year` | one product, heading or chapter under its section and chapter names: a world map of its suppliers with animated flows sized by share, a year slider that plays 2012 to 2024 and, on a click, what that supplier sells the reporter inside the code, supplier bars and a table with each supplier's distance, border and language, a bubble chart of supplier value against distance, the import-weighted distance and the share from neighbours by year, imports, exports, RCA and HHI from 2012 to 2024, supplier shares over time, for one product the 25 largest world exporters against what each sent the reporter, with their distance, border and language and filters for each, for one product the MFN tariff every market charges the reporter on a map and a sorted wall, with a dashed outline and a tick at the MFN rate where a preference applies where a range floats from its lowest to its highest rate, a hatched bar marks non-ad-valorem duties and a dot sized by value marks each market the reporter already sells to, for a heading or product the supplier network from the trade graph, and a link to its sea routes |
| `#/scenario?mode&code&year&suppliers&reduction` | product or supplier-country disruption, previewed live, saved as a report |
| `#/reports` and `#/reports/{id}` | the reporter's saved reports with provenance, limitations, CSV download and a print layout that keeps every table row |

Both maps zoom with the wheel, a pinch or the + and − buttons, and pan by dragging. Whole world resets them.
Maps use the 1:50m Natural Earth boundaries distributed in world-atlas 2.0.2.
Twin-map colors show relative similarity rank. Tooltips and bars keep the actual scores.

Charts with axes zoom with Ctrl and the wheel or a box drawn after their zoom
button, pans with a mouse drag and resets on a double-click. A plain wheel or
a finger still scrolls the page. Bar charts zoom along their categories only.
Scatter charts zoom both axes, which spreads a crowd of dots apart. The same
Save image downloads a PNG without the zoom controls. On phones, Menu opens
every page, and product, country and report details link back to their lists.

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

`pytest -q` runs 91 tests against a local MongoDB on port 27017. CI starts a
MongoDB 9.0 service for them.

`node --test tests/frontend.test.mjs` checks chart tooltip confinement, toolbar
spacing, zoom axes, reset and narrow-screen label settings without MongoDB.

| Guarantee | Tests |
| --- | --- |
| The blueprint example gives top share 60%, top 3 100%, HHI 0.46 | `test_metrics.py::test_blueprint_example` |
| Affected value is r × Σ selected, other suppliers unchanged | `test_api.py::test_product_scenario_follows_the_blueprint_rule` |
| Product search finds words in any order and in their plural, and still matches a half-typed word | `test_api.py::test_product_search_matches_words_in_any_order_and_half_typed_words` |
| Search puts a named chapter or heading, such as Wheat and meslin, before its products | `test_api.py::test_search_puts_a_named_heading_before_its_products` |
| HS names reach every product at section, chapter and heading level, a heading the source leaves out takes its first product's description, and the names change the snapshot id | `test_prepare.py::test_categories_name_every_level_and_fall_back_to_the_description`, `::test_hs_names_change_the_snapshot_id_and_join_each_product` |
| Each section, chapter and heading of the import tree is the exact sum of its products, and a snapshot without HS names answers 404 | `test_api.py::test_categories_sum_each_level_exactly`, `::test_categories_need_hs_names` |
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
| WITS and GeoDist codes, and the EU's shared schedule, reach the right BACI country, and a member's own schedule wins | `test_coverage.py::test_coverage_maps_source_codes_and_eu_schedules_to_baci` |
| GeoDist reaches BACI countries through its older codes, never pairs two countries inside one GeoDist entity, and reaches the partner views | `test_prepare.py::test_geography_maps_aliases_and_skips_pairs_inside_one_entity`, `::test_geography_changes_the_snapshot_id_and_is_stored_per_pair`, `test_api.py::test_partner_views_carry_geodist_distance_border_and_language` |
| The trade graph holds the last year once per exporter, importer and heading, and its value equals the world total | `test_prepare.py::test_graph_holds_the_last_year_once_per_exporter_importer_and_heading` |
| The supplier network finds the reporter's suppliers, markets sharing them, exporters not yet selling to it and two-step paths | `test_api.py::test_network_finds_shared_suppliers_other_exporters_and_two_step_paths` |
| A missing Ladybug graph or Milvus twins file answers 503 for its own panel while the MongoDB views keep answering | `test_api.py::test_a_missing_graph_or_twins_fails_only_its_own_panel` |
| Trade twins store one vector per trading country and flow, score an identical mix 1 and no shared product 0, and name the products behind each score | `test_api.py::test_twins_rank_countries_by_basket_overlap_and_name_what_they_share` |
| A tariff schedule keeps MFN rates as exact text and leaves out a line with no rate instead of reading it as zero, and several HS2017 codes in one HS2012 code keep a range, never an average | `test_tariffs.py::test_schedule_keeps_mfn_rates_as_exact_strings_and_leaves_out_a_missing_rate`, `::test_several_hs2017_codes_keep_a_range_and_never_an_average`, `::test_older_schedules_take_the_one_code_hs2012_maps_to` |
| Every market gets its own schedule's rate and the reporter's last-year sales to it, ranges stay ranges, and tariffs change the snapshot id | `test_api.py::test_tariffs_give_every_market_its_schedules_rate_and_keep_ranges` |
| A preference keeps its count of preferential lines and skips a rate WITS cannot compute | `test_tariffs.py::test_preferences_keep_their_preferential_line_count_and_skip_an_unknown_rate` |
| A market charges the reporter its best preference, a customs union charges nothing, a group with no known members is never applied, and the reporter's own schedule names the suppliers it favours | `test_api.py::test_a_market_charges_the_reporter_its_best_preference_and_a_customs_union_nothing` |
| A product's world exporters leave the reporter out and keep their share of world exports | `test_api.py::test_history_lists_world_exporters_without_the_reporter` |
| Country names CEPII encoded twice are repaired, clean names stay | `test_prepare.py::test_names_encoded_twice_are_repaired_and_clean_names_kept` |
| Route and chokepoint totals are sums of their countries, and routes follow the reporter | `test_api.py::test_routes_sum_countries_into_routes_and_chokepoints`, `::test_routes_follow_the_reporter`, `::test_the_route_depends_on_the_reporter` |
