**Recommendation: keep MongoDB for serving, add DuckDB for release preparation and country materialization, and keep one importer-partitioned Parquet copy of the flows. Precompute export aggregates and world inputs once per snapshot.** Use a bounded MongoDB cache so visiting every country does not eventually recreate the estimated 11 GB warehouse. This adds one Python dependency and no server. DuckDB is MIT-licensed. [1]

The export measures need product totals, destination totals and quantity coverage, saving a second complete bilateral-flow copy. This covers all existing import views and the five requested export measures. Full export destination-by-product drilldowns or export disruption scenarios would require another access path, outside these estimates.

Checked 16 October 2026. Estimated performance figures are planning budgets, not benchmarks.

**Practitioner evidence**

| Project | Publicly documented storage, computation and serving | Implication here |
| --- | --- | --- |
| Harvard Atlas | GraphQL exposes country-year, country-product-year, bilateral and product-year results, including RCA. Bulk downloads are pre-generated tables. Its physical database engine is not established by these sources. [2] | Copy the prepared grains and filtered queries. |
| OEC | Public website code routes BACI cube queries through Tesseract. Tesseract supports ClickHouse, PostgreSQL and MySQL backends and request caching. This does not establish the backend of every current OEC deployment. [4], [5] | OLAP precedent, without a reason to add another server here. |
| CEPII | Country Profiles publishes BACI concentration indicators alongside CHELEM data. Physical storage is undocumented in the inspected source. A CEPII research paper computes annual global PRODY from BACI for 1997-2007. [6], [24] | Prepare indicators at release time. |
| WITS | Explicitly pre-calculates country statistics. Its API serves indicators by reporter/partner/product/year and restricts broad requests. Physical storage is not established. [7], [8] | Prepare common results and scope requests. |
| Reyes's BACI scripts | Annual CSVs become Parquet, queried and aggregated with DuckDB. [9] | Closest small open-source precedent. |
| FitzGerald's BACI pipeline | PySpark/Dataproc writes year-partitioned Parquet to GCS, aggregate tables to BigQuery, then serves Looker Studio. [10] | Same separation, excessive infrastructure here. |

Bouaziz et al. evaluate document-oriented OLAP with MongoDB on COVID-19 data, supplying no BACI performance benchmark or reason to replace the serving store. [11]

**Sizes and times**

Decimal GB, 2012-2024. Derived storage excludes the 1.268 GB ZIP, country cache and operational overhead. Cold times include reading, calculation, BSON and writes for full history. Estimates assume an SSD, 4 available cores, 8-16 GB RAM and one build at a time.

| Option | Derived storage per release | One-time preparation | First country, full history | Subsequent API requests | Assessment and confidence |
| --- | --- | --- | --- | --- | --- |
| Rerun current ZIP importer | None, plus country cache | None | 1,052 s measured for Tunisia's current import path | Current medians 60-801 ms | Reject. High confidence in supplied baseline, no claim that every optimized ZIP reader takes 17 minutes. |
| Per-importer and per-exporter gzip CSV | About 2.6 GB proposed, budget 2.2-3.2 GB | 10-30 min estimated | Tunisia 5-20 s, larger countries 20-90 s estimated | Same MongoDB path | Viable simplest fallback. Size medium-low confidence, times low. Two complete flow projections and repeated CSV/Decimal work. |
| Two country-oriented Parquet flow projections, DuckDB or Polars | 1.8-3.2 GB estimated | 5-20 min estimated | Tunisia 2-10 s, larger countries 5-30 s estimated | Target 50-500 ms with serving changes below | Technically sound, but duplicates bilateral rows for exports that only need aggregates. Low confidence in unmeasured sizes/times. |
| **One importer Parquet projection plus export/world aggregates, DuckDB** | **0.9-1.6 GB flows plus 0.15-0.40 GB aggregates, total 1.05-2.0 GB estimated** | **5-15 min estimated** | **Tunisia 2-8 s, larger importers 5-20 s estimated** | **Target 50-500 ms, p95 below 1 s** | **Recommended.** Medium confidence in access-path suitability, low in size/time budgets until benchmarked. |
| Raw flows in MongoDB, indexed for both directions, plus lazy country documents | Rough planning allowance 6-15 GB raw data and indexes, plus cache | 20-90 min estimated | 3-30 s with suitable indexes, potentially much longer on cache misses or spills | Same MongoDB path after materialization | Reject on disk. All figures low confidence. `$merge` works, but does not remove raw storage or aggregation cost. [12] |
| Every country's existing import documents precomputed in MongoDB | About 10.9 GB imports by linear extrapolation, roughly 21.8 GB if a comparable export copy were also stored | Unmeasured, at least one full preparation and all writes | No country build | Current pages still need optimization | Reject on disk. Extrapolation has medium-low confidence because countries, compression and indexes differ. |

The 10.9 GB extrapolation is `55 MB × 142,112,452 / 717,531`. A minimal raw BSON flow encoded locally took 95 bytes: **13.50 GB uncompressed**, before indexes. Neither calculation measures all-country disk use. WiredTiger compression depends on data and codec. [13]

Budget **2.82-4.27 GB**, including ZIP and a 0.5-1.0 GB cache, plus journals, allocation overhead and reports. Prepare one year at a time, with an initial 2 GB scratch allowance to verify. Immutable storage grows approximately linearly with retained releases. Cache capacity is shared across releases.

Local archive SHA-256: `2dd0dd6174f11e9fc33b9bacf001d50c1913dbfeed9cba30876a1668b2b75bf9`. Inflating its 13 annual CSVs, **4,626,525,918 bytes**, into discarded 1 MiB buffers took **21.138 s**. This single non-Docker run allowed warm filesystem caches and performed no parsing or metrics. Profile the 17-minute importer beyond ZIP decompression.

A second single run scanned **11,109,411 rows of 2024** and compressed selected countries' unchanged lines at gzip level 6 in **29.740 s**, without measures or database writes:

| Country | Import rows | Export rows | Import gzip bytes | Export gzip bytes |
| --- | ---: | ---: | ---: | ---: |
| Tunisia | 53,271 | 44,809 | 491,524 | 388,672 |
| United States | 203,627 | 398,039 | 2,030,278 | 3,764,165 |
| China | 147,302 | 558,453 | 1,426,547 | 5,703,375 |
| Germany | 202,377 | 393,606 | 2,002,071 | 3,835,805 |
| Gabon | 18,866 | 2,050 | 169,597 | 17,979 |

These checks establish country-size variation, not full-release storage or build times. No proposed engine was benchmarked. A universal five-second load is unproven.

**Preparation and serving design**

Extract one annual CSV with stdlib `zipfile`. DuckDB validates explicit types and writes ZSTD Parquet partitioned by importer/year, sorted by HS6/exporter. Manifest exact paths. Start near 100,000-row groups for large partitions. Importer sorting alone does not accelerate arbitrary exporter queries. DuckDB documents partition pruning and row-group pushdown. [14], [15]

Keep one canonical flow projection. During the release build, compute:

- `exports(country, year, product)`: value, quantity-valid value, valid quantity, quantity coverage and RCA inputs.
- `destinations(country, year, destination)`: values for geographic HHI.
- `country_year`: import/export totals, export product/geographic HHI and EXPY.
- `world_product_year`: world product exports, sum of squared exporter totals, top six exporters, and the selected PRODY specification. Also retain world totals per year.

Store export-product aggregates in country-partitioned Parquet and small world/country-year summaries permanently in MongoDB. Pages never scan world flows.

Materialize the chosen country with bounded PyMongo batches. API reads stay in MongoDB. **Skip PyMongoArrow:** supported tabular writes do not solve the nested-document assembly needed here. [16] Keep the existing Decimal codec. Polars is an alternative engine, with no demonstrated advantage here. Install one engine.

Use a unique leased job per snapshot/country, hidden build generation and atomic ready pointer. The app can host the worker. Evict country generations by byte budget, preserving snapshots and reports. WiredTiger reuses deleted space without guaranteeing filesystem shrinkage. [13]

The 801 ms overview needs serving changes: scoped indexes, narrow projections, Tabulator pagination and precomputed chart totals. Response-cache keys must include snapshot, country, direction, year and every filter. Measure browser rendering separately.

**MongoDB documents and indexes**

Use one `country_product_years` document for the union of imported and exported HS6 products, keyed by `(snapshotId, countryCode, productCode, year)`. Keep optional blocks so an export-only product needs no artificial import record:

```text
snapshotId, countryCode, productCode: "010121", year
imports:
  partners: [{countryCode, valueUsd, quantityTonnes}]
  totalUsd, partnerCount, topPartnerCode, topShare, top3Share, hhi
exports:
  totalUsd, quantityValidValueUsd, validQuantityTonnes
  quantityCoverage, unitValueUsdPerTonne, rca, qualityFlags
```

Keep names in snapshot dictionaries and world metrics in shared `world_product_years`. `country_years` holds basket HHIs, EXPY, coverage and destination totals. Each cached import embeds its supplier detail once. Export blocks reuse aggregates. The cache necessarily duplicates part of its source.

The [current importer](../atlas/ingest.py) excludes the reporter's exports from its world comparator. Preserve that separately from inclusive RCA totals. With `W = sum_c X_ck`, `S2 = sum_c X_ck²`, and `x = X_reporter,k`, use `(S2 - x²)/(W - x)²`, null when `W = x`. Remove the reporter from the global top six to obtain five alternatives.

Create these indexes, with `1` ascending and `-1` descending:

| Collection | Index | Purpose |
| --- | --- | --- |
| `country_product_years` | Unique `(snapshotId:1, countryCode:1, productCode:1, year:1)` | Identity and product history |
| `country_product_years` | `(snapshotId:1, countryCode:1, year:1, imports.totalUsd:-1, productCode:1)` | Import overview, stable pagination and year reads |
| `country_product_years` | `(snapshotId:1, countryCode:1, year:1, exports.totalUsd:-1, productCode:1)` | Export overview |
| `country_product_years` | `(snapshotId:1, countryCode:1, imports.partners.countryCode:1, year:1)` | Existing supplier-country profile |
| `country_years`, materializations | Unique `(snapshotId:1, countryCode:1, year:1)` and unique `(snapshotId:1, countryCode:1)`, respectively | Summaries and one job per country |
| `world_product_years`, products | Unique `(snapshotId:1, productCode:1, year:1)` and unique `(snapshotId:1, productCode:1)`, respectively | Shared references |
| reports | `(snapshot.id:1, countryCode:1, createdAt:-1)` | Country-scoped report list |

Prepend `generationId` to cache indexes/queries, excluding the job identity and permanent summaries. Verify equality prefixes and sort plans with `explain("executionStats")`. [17] Keep product-year granularity. MongoDB limits documents to 16 MiB. [18]

**GDP, formulas and interpretation**

Choose **WDI `NY.GDP.PCAP.PP.KD`, GDP per capita, PPP, constant 2021 international dollars**, CC BY 4.0. It covers the trade window, subject to country gaps. PWT 11.0 is also CC BY 4.0, covers 185 countries through 2023 and has a numbered vintage, but lacks 2024. With PWT, divide GDP by population and specify expenditure/output and current/chained PPP. [19], [20]

Freeze WDI response bytes, metadata, indicator/source id, query, retrieval UTC, crosswalk, exclusions and SHA-256. Pin BACI hash, HS, code/dependencies, decimal rules and definitions in a manifest. Use `BACI_HS12_V202601@<manifest-hash>`: changed GDP or formulas create a new analysis snapshot. Preserve legacy ids/reports. CEPII warns against mixing releases because historical flows change. [21]

Let `X_ck = sum_j v_cjk`, `X_c = sum_k X_ck`, `X_k = sum_c X_ck`, and `X = sum_c X_c`, for a consistent year and country universe. Define `s_ck = X_ck/X_c`. The export measures are:

| Measure | Definition and required guard |
| --- | --- |
| RCA | `(X_ck/X_c)/(X_k/X)`. Null for a zero denominator. Include all eligible world exporters, regardless of which countries have been cached. Show export dollars and share beside RCA. Tiny baskets and tiny world markets can produce very large ratios. Keep raw RCA, with optional, versioned display thresholds rather than silently changing its denominator. |
| Product HHI | `sum_k s_ck²`, using the full HS6 basket. Aggregate values before computing an HS4/HS2 version. Do not average product HHIs. |
| Geographic HHI | `sum_j (sum_k v_cjk/X_c)²`. Aggregate across products by destination first. Missing/zero total gives null, not apparent perfect diversification. |
| EUV | For each country/HS6/year, `1000 × sum(v over valid-q flows)/sum(q over those same flows)` in USD/tonne. Report the included value share. Missing, nonfinite or nonpositive quantities yield no unit value. Never divide all value by only the observed quantities, average bilateral ratios unweighted, or publish a meaningful-looking basket unit value across unrelated products. |
| PRODY and EXPY | `PRODY_k = sum_c [s_ck/sum_a s_ak] × GDPpc_c`, using countries with eligible GDP and positive exports. `EXPY_c = sum_k s_ck × PRODY_k`. It measures income association, not technology or domestic value added directly. [24] |

CEPII warns that some Comtrade-processed BACI quantities are unsuitable for unit values. Flag extreme HS6/year ratios and tiny quantities. Preserve source values and version trimming sensitivities. EUV remains a price/mix proxy. CEPII's separate TUV addresses reliability but does not automatically cover this period. [23]

Recommended PRODY policy: **annual weights and same-year WDI income**, explicit eligible countries, no regional aggregates or silent forward fill. Renormalize among GDP-covered exporters and publish their world export coverage. RCA retains its separate world universe. Return main EXPY as null when products lack PRODY, with coverage and an optional labelled covered-basket result. Publish a common-country, fixed-2012 PRODY sensitivity to separate basket changes from income/coverage changes. These are analytical choices, distinct from the original index's definition. [22], [24]

Use BACI's country dictionary for the GDP crosswalk: its numeric codes can differ from ISO. Document special-territory/residual-code mappings and preserve HS6 leading zeros. [21]

**Migration and proof of country isolation**

1. Preserve Tunisia's snapshot/reports and baseline values. Profile parsing, validation, aggregation, BSON and writes separately.
2. Build the manifest and world/GDP inputs. Validate unique `(t,i,j,k)` keys, dictionaries, years and finite values. Audit scales before choosing Parquet DECIMAL types. Preserve Decimal/Decimal128 arithmetic. Bad quantity need not discard valid trade value.
3. Prepare one year at a time in a temporary directory. Check row/value totals and hashes, then publish atomically. Exclude generated data from git/images.
4. Add scoped collections and leased cache fills. Prove Tunisia parity, including its world comparator, and idempotent retries/eviction. Hide incomplete generations.
5. Require reporter scope throughout API queries, scenarios, reports, frontend state, URLs and cache keys. Distinguish reporter from partner in the existing country-profile route. Reports retain reporter, direction, manifest identity and computed results.
6. Add export views. Parameterize tests by country/direction/year/snapshot. Reject missing or invalid scope.
7. Benchmark Tunisia, USA, China and a small exporter under identical Compose limits. Record disk/indexes, peak RAM/scratch, full cache-miss time and p50/p95 API/browser times. Proposed gates: first-country readiness within 20 s and cached API p95 below 1 s. A universal 5 s requirement needs its own stricter benchmark.

Isolation fixture, one HS6/year, thousands of USD: `TUN→USA=60`, `USA→TUN=10`, `CHN→TUN=30`, `CHN→USA=40`. Assert imports **$40,000/$100,000**, exports **$60,000/$10,000**, import HHIs **0.625/0.52** for Tunisia/USA. A 50% China disruption exposes **$15,000/$20,000**.

Exercise overview, history, movers, partner profiles, scenarios, report lists, CSV and print. Repeat in reversed order, concurrently, after eviction/rebuild and with a second changed snapshot. Saved reports stay unchanged. Interrupt a build and assert every endpoint rejects its incomplete generation. Independently test world RCA totals, reporter-excluded HHI, quantity coverage and global import/export conservation.

Remove the query's country predicate and the cache key's country component, separately. The suite must fail for each mutation.

**Source list**

[1]: https://duckdb.org/faq
[2]: https://github.com/harvard-growth-lab/api-docs/blob/main/atlas.md
[3]: https://atlas.hks.harvard.edu/trade-data-methodology/
[4]: https://github.com/Datawheel/oec-website
[5]: https://github.com/tesseract-olap/tesseract
[6]: https://visiadata.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=30
[7]: https://blogs.worldbank.org/en/opendata/wits-trade-data-site-five-new-features
[8]: https://wits.worldbank.org/witsapiintro.aspx?lang=en
[9]: https://github.com/ksreyes/baci
[10]: https://github.com/DavidVFitzGerald/trade-flows-analysis
[11]: https://link.springer.com/article/10.1007/s10586-024-04776-x
[12]: https://www.mongodb.com/docs/manual/reference/operator/aggregation/merge/
[13]: https://www.mongodb.com/docs/manual/faq/storage/
[14]: https://duckdb.org/docs/current/data/partitioning/hive_partitioning
[15]: https://duckdb.org/docs/current/data/parquet/tips
[16]: https://www.mongodb.com/docs/languages/python/pymongo-arrow-driver/current/get-started/
[17]: https://www.mongodb.com/docs/manual/core/indexes/index-types/index-compound/sort-order/
[18]: https://www.mongodb.com/docs/manual/reference/limits/
[19]: https://data.worldbank.org/indicator/NY.GDP.PCAP.PP.KD
[20]: https://www.rug.nl/ggdc/productivity/pwt/
[21]: https://www.cepii.fr/DATA_DOWNLOAD/baci/doc/baci_webpage.html
[22]: https://www.nber.org/papers/w11905
[23]: https://www.economie-internationale.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=2
[24]: https://www.cepii.fr/PDF_PUB/wp/2009/wp2009-34.pdf

1. [DuckDB FAQ, licensing and embedded storage][1].
2. [Harvard Atlas API documentation][2] and [trade methodology][3].
3. [OEC website source][4] and [Tesseract engine source][5].
4. [CEPII Country Profiles][6].
5. [World Bank's explanation of WITS precomputation][7] and [WITS API][8].
6. [Reyes's DuckDB/Parquet BACI project][9] and [FitzGerald's cloud BACI pipeline][10].
7. [Bouaziz et al., document-oriented OLAP, 2025][11]. The [2019 schema paper](https://doi.org/10.1016/j.procs.2019.09.177) was identified, but its full text was not retrieved and supplies no performance claim here.
8. [MongoDB `$merge`][12], [storage][13], [compound sort indexes][17] and [limits][18].
9. [DuckDB partition pruning][14] and [Parquet layout guidance][15].
10. [PyMongoArrow supported writes][16].
11. [WDI GDP per capita PPP and its licence][19] and [PWT coverage, definitions and licence][20].
12. [CEPII BACI definitions, country codes and revision policy][21].
13. [Hausmann, Hwang and Rodrik, What You Export Matters][22] and [Jarreau/Poncet's BACI implementation, equations 1-2 and section 2.2][24].
14. [CEPII's warning about BACI quantities and the TUV alternative][23].

Local evidence: the supplied measurements, the repository's [README](../README.md), [importer](../atlas/ingest.py), [database indexes](../atlas/db.py) and [API](../atlas/api.py), plus the two limited archive checks described above. The proposed Parquet layout, materialization times and page-latency targets remain unbenchmarked.
