"""Who sells each HS4 heading to whom, as a Ladybug graph, and the questions the product page asks it.

Countries are nodes, and each exporter's flow of a heading to an importer is
one directed TRADE edge with its value in whole US dollars. BACI's thousands
of dollars carry three decimals, so whole dollars lose nothing, and Ladybug
cannot read Parquet decimals. An edge links two trading partners. It is not a
proven supply chain or a shipping route.

ponytail: one year and HS4 only, which keeps the file to a few million edges.
Add a year property to the edges if the network over time matters.
"""

from functools import lru_cache

import ladybug

TOP = 10


def build(path, countries, edges):
    """Write the graph from an edges Parquet of (exporter, importer, heading, valueUsd) and return its edge count and value."""
    db = ladybug.Database(str(path))
    con = ladybug.Connection(db)
    try:
        con.execute("CREATE NODE TABLE Country(code INT64 PRIMARY KEY)")
        con.execute("CREATE REL TABLE TRADE(FROM Country TO Country, heading STRING, valueUsd INT64)")
        con.execute("UNWIND $codes AS c CREATE (:Country {code: c})", {"codes": countries})
        if edges:
            con.execute(f"COPY TRADE FROM '{edges.as_posix()}'")
        n, value = con.execute("MATCH ()-[t:TRADE]->() RETURN count(t), coalesce(sum(t.valueUsd), 0)").get_all()[0]
        return n, int(value)
    finally:
        con.close()
        db.close()


@lru_cache(maxsize=4)
def opened(path):
    return ladybug.Database(str(path), read_only=True)


def network(path, reporter, heading):
    """The reporter's suppliers of one heading, the markets sharing them, exporters not yet selling to it, and two-step paths.

    Every query names the heading and the reporter, and paths stop at two steps,
    so no traversal walks the whole graph.
    """
    con = ladybug.Connection(opened(path))
    params = {"r": reporter, "h": heading}

    def rows(query, **extra):
        return con.execute(query, params | extra).get_all()

    try:
        suppliers = rows(
            "MATCH (s:Country)-[t:TRADE {heading: $h}]->(:Country {code: $r})"
            f" RETURN s.code, t.valueUsd ORDER BY t.valueUsd DESC, s.code LIMIT {TOP}"
        )
        peers = rows(
            "MATCH (s:Country)-[:TRADE {heading: $h}]->(:Country {code: $r}), (s)-[t:TRADE {heading: $h}]->(m:Country)"
            " WHERE m.code <> $r RETURN m.code, count(s) AS shared, sum(t.valueUsd) AS v"
            f" ORDER BY shared DESC, v DESC, m.code LIMIT {TOP}"
        )
        alternatives = rows(
            "MATCH (x:Country)-[t:TRADE {heading: $h}]->(m:Country)"
            " WHERE x.code <> $r AND NOT EXISTS { MATCH (x)-[:TRADE {heading: $h}]->(:Country {code: $r}) }"
            f" RETURN x.code, count(m) AS markets, sum(t.valueUsd) AS v ORDER BY v DESC, x.code LIMIT {TOP}"
        )
        paths = rows(
            "MATCH (o:Country)-[a:TRADE {heading: $h}]->(s:Country)-[:TRADE {heading: $h}]->(:Country {code: $r})"
            f" WHERE o.code <> $r RETURN o.code, s.code, a.valueUsd ORDER BY a.valueUsd DESC, o.code LIMIT {TOP}"
        )
        sellers = [s for s, _ in suppliers] + [x for x, *_ in alternatives]
        links = rows(
            "MATCH (s:Country)-[t:TRADE {heading: $h}]->(m:Country) WHERE s.code IN $s AND m.code IN $m"
            " RETURN s.code, m.code, t.valueUsd ORDER BY s.code, m.code",
            s=sellers, m=[m for m, *_ in peers],
        )
    finally:
        con.close()
    return {
        "suppliers": [{"countryCode": s, "valueUsd": v} for s, v in suppliers],
        "peers": [{"countryCode": m, "sharedSuppliers": n, "valueUsd": int(v)} for m, n, v in peers],
        "alternatives": [{"countryCode": x, "markets": n, "valueUsd": int(v)} for x, n, v in alternatives],
        "paths": [{"origin": o, "via": s, "valueUsd": v} for o, s, v in paths],
        "links": [{"from": s, "to": m, "valueUsd": v} for s, m, v in links],
    }
