# tests

`pytest -q` runs 96 tests against MongoDB on port 27017, in a database of its own, `atlas_test`, dropped before each test. CI starts a MongoDB 9.0 service for them.

```bash
pytest -q
```

`node --test` runs 8 frontend tests without MongoDB: tooltip confinement, toolbar spacing, zoom axes, reset, narrow-screen labels and the browser cache.

```bash
node --test tests/frontend.test.mjs
```

| File | Covers |
| --- | --- |
| [`test_metrics.py`](test_metrics.py) | the formulas in `metrics.py` |
| [`test_prepare.py`](test_prepare.py) | preparation, snapshots, geography, the graph |
| [`test_tariffs.py`](test_tariffs.py) | WITS schedules and preferences |
| [`test_coverage.py`](test_coverage.py) | WITS and GeoDist codes to BACI countries |
| [`test_db.py`](test_db.py) | the Decimal128 codec |
| [`test_api.py`](test_api.py) | endpoints, country views, scenarios, reports, twins, routes |
| [`frontend.test.mjs`](frontend.test.mjs) | chart settings and the browser cache |

## Guarantees

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
| Decimals reach MongoDB as the same Decimal128 bits pymongo writes, and read back unchanged | `test_db.py::test_decimal_codec_matches_pymongo_bit_for_bit` |
| Codes keep leading zeros, values convert exactly, missing tonnes stay null | `test_prepare.py::test_leading_zeros_survive`, `::test_values_are_converted_from_thousands_of_usd_exactly`, `::test_missing_quantity_stays_missing` |
| Bad rows go to the error report with their line | `test_prepare.py::test_untrusted_rows_go_to_the_error_report`, `::test_each_broken_row_is_named_with_its_line` |
| Preparing twice is idempotent, a missing year fails the snapshot | `test_prepare.py::test_preparing_twice_creates_no_duplicates`, `::test_missing_year_fails_the_snapshot` |
| The world comparison leaves the reporter out | `test_prepare.py::test_metrics_and_world_comparison_leave_the_reporter_out` |
| RCA, unit values, PRODY and EXPY | `test_prepare.py::test_exports_carry_rca_unit_value_and_coverage`, `::test_prody_and_expy_use_same_year_income` |
| One reporter never sees another's flows | `test_api.py::test_each_reporter_sees_only_its_own_flows_whatever_the_visit_order` |
| Country views survive eviction, failure and an expired lease | `test_api.py::test_an_evicted_view_is_rebuilt_with_the_same_figures`, `::test_a_failed_build_leaves_nothing_readable`, `::test_a_build_whose_lease_expired_is_taken_over` |
| A first visit opens on the first and last years, and an unfinished fill is taken over | `test_api.py::test_a_first_visit_opens_on_the_first_and_last_years_and_fills_in_the_rest`, `::test_a_fill_that_stopped_is_taken_over_once_its_lease_expires` |
| A restart rebuilds the 3 countries visited last, the latest kept newest | `test_api.py::test_a_restart_rebuilds_the_countries_visited_last_the_latest_last` |
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
