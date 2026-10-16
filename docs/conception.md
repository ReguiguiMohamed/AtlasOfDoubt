# Conception

Four diagrams of how AtlasOfDoubt is built. The field-level detail lives in
the [data dictionary](data-dictionary.md).

## Classes

The Python side is four modules. Every number the API returns or a report
stores goes through `metrics`, so a live preview and a saved report cannot
disagree.

```mermaid
classDiagram
    class metrics {
        CALCULATION_VERSION
        total(suppliers) Decimal
        with_shares(suppliers) list
        summarize(suppliers) dict
        merge(supplier_lists) list
        scenario(suppliers, selected, reduction) dict
    }
    class ingest {
        YEARS
        REPORTER_ISO3
        ingest(path, db) dict
        read_year(archive, name, year, ...) tuple
        read_dictionary(archive, name, columns) list
        world_summary(exporters, countries) dict
    }
    class ErrorReport {
        counts
        samples
        reject(kind, file, line, row)
        as_doc() dict
    }
    class db {
        DecimalCodec
        connect() tuple
    }
    class api {
        GET /api/snapshots
        GET /api/products
        GET /api/overview
        GET /api/products/code/history
        POST /api/scenarios/preview
        POST /api/reports
        GET /api/reports
        GET /api/reports/id
        GET /api/reports/id.csv
    }
    ingest --> metrics : summarize
    ingest --> db : connect
    ingest *-- ErrorReport
    api --> metrics : summarize, merge, scenario
    api --> db : connect
```

## MongoDB documents

One snapshot per imported BACI release. Its product years and products carry
the snapshot id, so two releases sit side by side and a report keeps
pointing at the one it was computed from.

```mermaid
erDiagram
    snapshots ||--o{ product_years : "snapshotId"
    snapshots ||--o{ products : "snapshotId"
    snapshots ||--o{ reports : "snapshot.id (copied)"
    snapshots {
        string _id "BACI_HS12_V202601"
        string status "importing, ready or failed"
        object source "name, release, citation, licence, units"
        object archive "filename, sha256, bytes, retrievedAt"
        array years "2012 to 2024"
        object reporter "Tunisia, 788, TUN"
        array countries "BACI country dictionary"
        array files "rows per annual file"
        object counts "rows, tunisiaRows, products, suppliers"
        object errors "rejectedRows, byKind, samples"
    }
    product_years {
        string snapshotId
        string productCode "six digits, kept as text"
        int year
        string description
        array suppliers "countryCode, valueUsd, quantityTonnes"
        object metrics "totalUsd, topSupplier, top3Share, hhi"
        object world "world exporter totals and hhi"
    }
    products {
        string snapshotId
        string productCode
        string description
        string chapter "two digits"
        string heading "four digits"
        array importYears
    }
    reports {
        ObjectId _id
        string title
        date createdAt
        object spec "snapshot, year, mode, productCode, suppliers, reduction"
        object snapshot "id, source and archive at save time"
        string calculationVersion
        array limitations
        object result "frozen scenario output"
    }
```

Indexes:

| Collection | Index | Why |
| --- | --- | --- |
| `product_years` | `snapshotId, productCode, year` unique | one document per flow cell, and prefix search on a chapter or heading |
| `product_years` | `snapshotId, year` | the overview and country scenarios read a whole year |
| `products` | `snapshotId, productCode` unique | product search and group lookup |
| `reports` | `createdAt` descending | newest reports first |

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
    API->>DB: product_years.find(snapshot, code, year)
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
    CEPII[(CEPII BACI zip<br>1.27 GB)] -->|python -m atlas.ingest| Ingest[ingest]
    subgraph compose[docker compose]
        App[app: uvicorn atlas.api:app<br>port 8000]
        Mongo[(mongo 9.0<br>volume mongo)]
    end
    Ingest --> Mongo
    App --> Mongo
    Browser[Browser<br>ECharts, Tabulator] -->|HTTP| App
```

The archive is mounted read-only at `/data/raw` inside the app container
and never enters git or the image.
