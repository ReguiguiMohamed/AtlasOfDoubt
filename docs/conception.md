# Conception

Four diagrams of how AtlasOfDoubt is built. The field-level detail lives in
the [data dictionary](data-dictionary.md).

## Classes

The Python side is six modules. Every number the API returns or a report
stores goes through `metrics`, so a live preview and a saved report cannot
disagree.

```mermaid
classDiagram
    class metrics {
        CALCULATION_VERSION
        summarize(suppliers) dict
        merge(supplier_lists) list
        scenario(suppliers, selected, reduction) dict
        hhi(values) Decimal
        rca(x_ck, x_c, x_k, x) Decimal
        prody(baskets, gdp) dict
        expy(basket, prody) dict
        quality_flags(...) list
    }
    class prepare {
        YEARS
        DATA
        prepare(path, db, gdp_path) dict
        check_year(con, csv_path, ...) dict
        write_year(con, out, year, record)
        summarize_year(con, ...) tuple
        read_gdp(path, country_rows) tuple
    }
    class materialize {
        CACHE_BYTES
        LEASE
        ensure(db, snapshot, country) str
    }
    class routes {
        plan(reporter_iso) list
        route(reporter_iso, partner_iso) dict
    }
    class db {
        DecimalCodec
        connect() tuple
    }
    class api {
        GET /api/snapshots
        GET /api/overview
        GET /api/exports
        GET /api/products/code/history
        GET /api/countries/code
        GET /api/routes
        POST /api/scenarios/preview
        POST /api/reports
    }
    prepare --> metrics : hhi, prody, expy
    prepare --> db : connect
    materialize --> metrics : summarize, rca, quality_flags
    materialize --> prepare : DATA
    api --> materialize : ensure
    api --> metrics : merge, scenario
    api --> routes : plan
    api --> db : connect
```

## Stored data

A snapshot is one prepared release. Its flows live as Parquet under
`data/snapshots/{id}/`, partitioned by importer and year, beside a manifest
with every file's rows and SHA-256. MongoDB holds the snapshot record, the
world and country-year aggregates, and one generation of documents per
country that has been visited.

```mermaid
erDiagram
    snapshots ||--o{ products : "snapshotId"
    snapshots ||--o{ world_product_years : "snapshotId"
    snapshots ||--o{ country_years : "snapshotId"
    snapshots ||--o{ materializations : "snapshotId"
    materializations ||--o{ country_product_years : "generationId"
    snapshots ||--o{ reports : "snapshot.id (copied)"
    snapshots {
        string _id "BACI_HS12_V202601@hash"
        string status "preparing, ready, failed or legacy"
        object source "name, release, citation, licence, units"
        object archive "filename, sha256, bytes, retrievedAt"
        object manifest "input hashes and versions"
        object storage "path, files, bytes, manifestSha256"
        array years "2012 to 2024"
        array countries "BACI country dictionary"
        object worldTotals "world exports per year"
        object gdp "WDI indicator and coverage, or null"
        object errors "rejectedRows, byKind, samples"
    }
    products {
        string snapshotId
        string productCode "six digits, kept as text"
        string description
        string chapter "two digits"
        string heading "four digits"
    }
    world_product_years {
        string snapshotId
        string productCode
        int year
        Decimal totalUsd
        Decimal sumSquares "for the HHI without one country"
        array topExporters
        Decimal prody
    }
    country_years {
        string snapshotId
        int countryCode
        int year
        Decimal importsUsd
        Decimal exportsUsd
        Decimal productHhi
        Decimal geoHhi
        object expy
        array destinations
    }
    materializations {
        string snapshotId
        int countryCode
        string generationId
        string status "building, ready or failed"
        date leaseUntil
        date lastUsedAt
        int bytes
    }
    country_product_years {
        string generationId
        string productCode
        int year
        object imports "suppliers, metrics, world without the reporter"
        object exports "totalUsd, rca, worldShare, unit value, qualityFlags"
    }
    reports {
        ObjectId _id
        string title
        object reporter "countryCode, countryName, isoCode"
        object spec "snapshot, reporter, year, mode, productCode, suppliers, reduction"
        object snapshot "id, source and archive at save time"
        string calculationVersion
        object result "frozen scenario output"
    }
```

Indexes:

| Collection | Index | Why |
| --- | --- | --- |
| `products` | `snapshotId, productCode` unique | product search and group lookup |
| `world_product_years` | `snapshotId, productCode, year` unique | the world side of a country build |
| `country_years` | `snapshotId, countryCode, year` unique | the export trend of one reporter |
| `materializations` | `snapshotId, countryCode` unique | one build job per country, claimed atomically |
| `country_product_years` | `generationId, productCode, year` unique | one document per cell, and prefix search on a chapter or heading |
| `country_product_years` | `generationId, year, imports.metrics.totalUsd` and `exports.totalUsd` | the overview and the exports page read a whole year, largest first |
| `country_product_years` | `generationId, imports.suppliers.countryCode, year` | a partner country's profile |
| `reports` | `reporter.countryCode, createdAt` descending | a reporter's newest reports first |

## Saving a report

The browser sends only the scenario specification. The server reloads the
supplier values and recomputes, so a number typed or tampered with in the
browser never reaches a report.

```mermaid
sequenceDiagram
    actor Analyst
    participant Browser
    participant API as FastAPI
    participant M as metrics
    participant DB as MongoDB
    Analyst->>Browser: pick product, suppliers, reduction
    Browser->>API: POST /api/scenarios/preview {spec}
    API->>DB: snapshots.find_one(ready)
    API->>DB: materializations.find_one(snapshot, reporter)
    API->>DB: country_product_years.find(generation, code, year)
    API->>M: scenario(suppliers, selected, reduction)
    M-->>API: affectedUsd, exposureShare, remaining HHI
    API-->>Browser: {spec, calculationVersion, result}
    Analyst->>Browser: title, Save evidence report
    Browser->>API: POST /api/reports {spec, title}
    API->>DB: reload suppliers and recompute
    API->>DB: reports.insert_one(spec, snapshot provenance, result)
    API-->>Browser: 201 {id}
    Browser->>API: GET /api/reports/{id}
    API->>DB: reports.find_one(id)
    API-->>Browser: frozen report
```

## Deployment

```mermaid
flowchart LR
    CEPII[(CEPII BACI zip<br>1.27 GB)] -->|python -m atlas.prepare| Prepare[prepare]
    WDI[(WDI GDP json)] --> Prepare
    subgraph compose[docker compose]
        App[app: uvicorn atlas.api:app<br>port 8000]
        Mongo[(mongo 9.0<br>volume mongo)]
        Parquet[(data/snapshots<br>Parquet)]
    end
    Prepare --> Mongo
    Prepare --> Parquet
    App --> Mongo
    App -->|first visit| Parquet
    Browser[Browser<br>ECharts, Tabulator] -->|HTTP| App
```

The archive is mounted read-only at `/app/data/raw` and the prepared
snapshots at `/app/data/snapshots`. Neither enters git or the image.
