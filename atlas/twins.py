"""Trade twins: countries whose import or export basket looks alike, as sparse vectors in Milvus Lite.

Each country is one vector per flow, keyed by the HS6 code as an integer, and
each value is the square root of the product's share of the country's total.
Every vector then has unit length, and the inner product of two of them is the
Bhattacharyya coefficient of the two baskets: 1 for identical shares, 0 when
they share no product. The square root keeps one large product from deciding
the score alone. Twins trade alike. They are not linked by trade with each other.

ponytail: one year only, like the graph. Add a year field if twins over time matter.
"""

from functools import lru_cache
from math import sqrt

from milvus_lite import server_manager_instance
from pymilvus import DataType, MilvusClient

FLOWS = ("imports", "exports")
TOP = 10
SHARED = 3


def vectors(rows):
    """Turn (country, product, value) rows into {country: {int(product): sqrt(share)}}."""
    totals, baskets = {}, {}
    for country, product, value in rows:
        totals[country] = totals.get(country, 0) + value
        baskets.setdefault(country, {})[int(product)] = value
    return {c: {k: sqrt(v / totals[c]) for k, v in b.items()} for c, b in baskets.items() if totals[c] > 0}


def build(path, baskets):
    """Write one collection per flow from {flow: (country, product, value) rows} and return each flow's row count."""
    client = MilvusClient(str(path))
    try:
        written = {}
        for flow in FLOWS:
            schema = client.create_schema(auto_id=False)
            schema.add_field("code", DataType.INT64, is_primary=True)
            schema.add_field("basket", DataType.SPARSE_FLOAT_VECTOR)
            index = client.prepare_index_params()
            index.add_index("basket", index_type="SPARSE_INVERTED_INDEX", metric_type="IP")
            client.create_collection(flow, schema=schema, index_params=index)
            rows = [{"code": int(c), "basket": v} for c, v in sorted(vectors(baskets[flow]).items())]
            if rows:
                client.insert(flow, rows)
            client.flush(flow)
            written[flow] = client.get_collection_stats(flow)["row_count"]
        return written
    finally:
        client.close()
        # pymilvus serves a .db path from a gRPC thread that close() leaves running, and on Windows it holds the folder open.
        server_manager_instance.release_server(str(path))


@lru_cache(maxsize=4)
def opened(path):
    client = MilvusClient(str(path))
    for flow in FLOWS:
        client.load_collection(flow)
    return client


def twins(path, flow, reporter):
    """Every country's similarity to the reporter, and the products that make the closest ones alike.

    Returns None when the reporter has no trade in the flow. Countries that share
    no product with it are left out, so their similarity is 0.
    """
    client = opened(path)
    own = client.get(flow, ids=[reporter], output_fields=["basket"])
    if not own:
        return None
    mine = own[0]["basket"]
    hits = client.search(flow, data=[mine], anns_field="basket", limit=client.get_collection_stats(flow)["row_count"], output_fields=["code"])[0]
    scores = [{"countryCode": h["code"], "similarity": min(h["distance"], 1.0)} for h in hits if h["code"] != reporter]
    closest = scores[:TOP]
    theirs = {r["code"]: r["basket"] for r in client.get(flow, ids=[s["countryCode"] for s in closest], output_fields=["basket"])} if closest else {}
    for s in closest:
        basket = theirs[s["countryCode"]]
        # Each product adds sqrt(p * q) to the score, so the largest terms are what the two baskets share most.
        terms = sorted(((mine[k] * v, k) for k, v in basket.items() if k in mine), reverse=True)[:SHARED]
        s["shared"] = [{"productCode": f"{k:06d}", "contribution": c, "share": mine[k] ** 2, "twinShare": basket[k] ** 2} for c, k in terms]
    return {"similar": scores, "closest": closest}
