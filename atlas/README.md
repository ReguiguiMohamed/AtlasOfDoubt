# atlas

The Python package. `python -m atlas.prepare` turns a BACI release into a snapshot, and `uvicorn atlas.api:app` serves the API and the [web app](static/README.md) from one process.

## Modules

| File | Runs | Does |
| --- | --- | --- |
| [`prepare.py`](prepare.py) | once per release | checks the 13 yearly files in DuckDB, writes Parquet, world and country-year aggregates, GeoDist pairs, tariffs, HS names, the graph and the twins |
| [`materialize.py`](materialize.py) | first visit to a country | builds its import and export view from its Parquet partition into MongoDB |
| [`metrics.py`](metrics.py) | everywhere | totals, shares, top-3 share, HHI, RCA, unit values, PRODY, EXPY and the scenario |
| [`api.py`](api.py) | server | read endpoints scoped by `snapshot` and `reporter`, scenarios, reports, CSV, the static mount |
| [`graph.py`](graph.py) | preparation, product page | the Ladybug trade graph and its Cypher queries |
| [`twins.py`](twins.py) | preparation, imports and exports | the Milvus Lite basket vectors and their ranking |
| [`routes.py`](routes.py) | every request | the modelled sea lane from each partner to the reporter |
| [`coverage.py`](coverage.py) | before tariffs | matches WITS and GeoDist codes to BACI countries in `coverage.csv` |
| [`tariffs.py`](tariffs.py) | before tariffs | downloads WITS/TRAINS schedules and maps them to HS2012 |
| [`db.py`](db.py) | everywhere | the connection, Decimal128 codec and indexes |

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB server |
| `ATLAS_DB` | `atlas` | database name, `atlas_test` for the tests |
| `ATLAS_DATA` | `data/snapshots` | where prepared snapshots live |

## Run without Docker

Python 3.12 and MongoDB on port 27017.

```bash
pip install -e ".[dev]"
```

```bash
python -m atlas.prepare data/raw/BACI_HS12_V202601.zip
```

```bash
uvicorn atlas.api:app
```

Prepare fetches the World Bank GDP file, the two CEPII GeoDist files and the HS name files on its first run and keeps them in `data/snapshots/`.

## Tariffs

Optional. These fetch about 1,500 WITS files, the latest schedule of every BACI country and each partner's preferences, and prepare picks them up on its next run.

```bash
python -m atlas.coverage data/raw/BACI_HS12_V202601.zip
```

```bash
python -m atlas.tariffs
```

| Case | Rule |
| --- | --- |
| Schedule in HS2012 | keeps its rates |
| Schedule in HS2007 or HS2002 | each HS2012 code takes the one older code WITS maps it to |
| Several HS2017 codes in one HS2012 code | keeps their lowest and highest rate, never an average |
| EU members | share the EUN schedule, stored once |
| Preference for a group | applied through the 2018 TRAINS beneficiaries file, a group with no listed members is never applied |
| Rate charged to the reporter | the lower of MFN and the best preference covering it, zero inside a customs union |

## Snapshots

```bash
python -m atlas.prepare data/raw/BACI_HS12_V202701.zip
```

- The id is the archive name plus a hash of every input, such as `BACI_HS12_V202601@537b2fe453e3`.
- Preparing the same files twice returns the existing snapshot.
- A new release, GDP file, tariff file or formula gives a new id beside the old one.
- Work happens in a `.partial` folder renamed only when every year is written.
- Every request names its snapshot, and reports copy its source and archive hash.

## Stores

| Store | Holds | Read by |
| --- | --- | --- |
| Parquet | every valid flow, by importer and year | the first visit to a country |
| MongoDB | world and country-year aggregates, country views, tariffs, reports | every page |
| Ladybug `graph.lbug` | last year, one edge per exporter, importer and HS4 heading | the supplier network |
| Milvus Lite `twins.db` | one sparse vector of square-rooted HS6 shares per country and flow | trade twins |

The twin score is the inner product of two vectors, the Bhattacharyya coefficient of the two baskets: 1 for the same mix, 0 when no product is shared. A missing graph or twins file answers 503 for its own panel while the rest keeps working.

## One set of numbers

- Only `metrics.py` does arithmetic, so a preview and the report saved from it come from the same function.
- Values stay `Decimal` from the CSV text to the API, and the CSV export writes exact decimal text.
- Reports carry `CALCULATION_VERSION`.

## Country views

- A first visit builds the country's view under one generation id, readable only once complete.
- The first and last years come first, so the imports page opens while the other 11 fill in.
- The product, partner and sea route pages chart every year. They open on those two years as well and redraw once the fill is done.
- Two years build at once, and background fills take one of the two slots at most.
- A second request during a build waits for it, and a build whose 10 minute lease expired is taken over.
- Past 4 GB the least recently used views are dropped and rebuilt with the same figures.
- A restart rebuilds the 3 countries visited last.
- Decimal128 values are packed with integer arithmetic, since pymongo converts each of a country's 2.6 million decimals bit by bit in Python.

## Sea routes

BACI records who sold what, not how it travelled. [`routes.py`](routes.py) puts each country in one sea region with a hub port and joins the regions by usual lanes. A partner's route is the shortest path from its hub to the reporter's, so the value behind Suez or Hormuz estimates exposure and is no shipping record.

- Partners in the reporter's own region pass no chokepoint.
- A country no region lists is counted as unrouted.
