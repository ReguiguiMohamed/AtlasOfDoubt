"""Modelled sea routes between world regions, through the chokepoints between them.

BACI records who sold what, not how it travelled. Every country belongs to
one sea region with a hub port, and the regions are joined by usual sea
lanes through junctions and chokepoints. A partner's route to the reporter is
the shortest path from its hub to the reporter's hub, so the value behind a
strait is an estimate of exposure, not a shipping record. Coordinates are
[longitude, latitude]. Waypoints stay at sea on the 1:110m world map the app
draws, which closes the narrowest straits, so a few sit where that map still
shows water.

ponytail: every country in a region shares its hub as its port, and overland
neighbours in different regions are routed by sea. Give a country its own
port and land edges if a single region's figures start to matter.
"""

import heapq
import math
from functools import lru_cache

CHOKEPOINTS = {
    "gibraltar": {"name": "Strait of Gibraltar", "at": [-5.6, 35.88]},
    "suez": {"name": "Suez Canal", "at": [32.35, 30.55]},
    "bab": {"name": "Bab el-Mandeb", "at": [43.35, 12.6]},
    "hormuz": {"name": "Strait of Hormuz", "at": [56.45, 26.55]},
    "malacca": {"name": "Strait of Malacca", "at": [100.9, 2.6]},
    "turkish": {"name": "Turkish Straits", "at": [29.05, 41.1]},
    "danish": {"name": "Danish Straits", "at": [12.62, 55.95]},
    "panama": {"name": "Panama Canal", "at": [-79.7, 9.15]},
}

REGIONS = [
    {
        "id": "east-asia",
        "name": "East and Southeast Asia",
        "hub": [123, 30.5],
        "countries": "CHN HKG MAC S19 JPN KOR PRK MNG VNM THA KHM LAO PHL IDN MYS SGP BRN TLS",
    },
    {"id": "south-asia", "name": "South Asia", "hub": [72.6, 18.8], "countries": "IND PAK BGD LKA NPL BTN MDV MMR AFG"},
    {
        "id": "oceania",
        "name": "Oceania",
        "hub": [151.6, -34],
        "countries": "AUS NZL PNG FJI SLB VUT NCL PYF WSM TON KIR TUV NRU FSM MHL PLW GUM MNP ASM COK NIU TKL WLF PCN NFK CXR CCK PUS",
    },
    {"id": "gulf", "name": "Persian Gulf", "hub": [50.5, 27.5], "countries": "SAU ARE QAT KWT BHR IRQ IRN"},
    {
        "id": "east-africa",
        "name": "Arabian Sea and East Africa",
        "hub": [40, -4.2],
        "countries": "OMN YEM DJI ETH SOM KEN TZA MOZ MDG MUS SYC COM MYT UGA RWA BDI ZMB MWI ZWE SSD",
    },
    {"id": "red-sea", "name": "Red Sea", "hub": [38.6, 21.5], "countries": "JOR SDN ERI"},
    {
        "id": "black-sea",
        "name": "Black Sea and Central Asia",
        "hub": [37.6, 44.6],
        "countries": "RUS UKR ROU BGR GEO MDA KAZ BLR ARM UZB TKM KGZ TJK",
    },
    {"id": "baltic", "name": "Baltic", "hub": [18.8, 55], "countries": "SWE FIN EST LVA LTU POL"},
    {"id": "north-sea", "name": "North Sea and Atlantic Europe", "hub": [3.7, 52.2], "countries": "GBR IRL NLD BEL DEU DNK NOR ISL PRT"},
    {
        "id": "americas",
        "name": "North and Central America and the Caribbean",
        "hub": [-73.5, 40.3],
        "countries": "USA CAN MEX CUB DOM HTI JAM TTO BHS BRB ATG DMA GRD KNA LCA VCT ABW CUW BES SXM ANT BLM AIA VGB CYM TCA MSR BMU"
        " GTM HND SLV NIC CRI PAN BLZ VEN COL GUY SUR GRL SPM",
    },
    {"id": "south-atlantic", "name": "South America, Atlantic coast", "hub": [-46, -24.4], "countries": "BRA ARG URY PRY FLK"},
    {
        "id": "west-africa",
        "name": "West and Southern Africa",
        "hub": [-4, 4.9],
        "countries": "SEN CIV GHA NGA CMR GAB COG COD AGO NAM ZAF ZA1 MRT GIN SLE LBR TGO BEN GNQ GMB GNB CPV STP MLI BFA NER TCD CAF"
        " BWA LSO SWZ SHN",
    },
    {"id": "pacific-south-america", "name": "South America, Pacific coast", "hub": [-77.6, -12.1], "countries": "CHL PER ECU BOL"},
    {
        "id": "mediterranean",
        "name": "Mediterranean and overland",
        "hub": [11.5, 37.4],
        "countries": "TUN ITA FRA ESP GRC MLT CYP TUR LBY DZA MAR EGY ISR LBN SYR PSE SVN HRV ALB MNE BIH SRB MKD MCO SMR AND AUT CHE HUN"
        " CZE SVK LUX LIE AZE GIB",
    },
]

JUNCTIONS = {
    "aden": [52.2, 12.4],
    "ceylon": [80.6, 5.3],
    "cape": [19, -36],
    "iberia": [-9.9, 36.6],
    "ushant": [-5.8, 48.6],
    "antilles": [-63, 18.8],
}

PLACES = {**JUNCTIONS, **{c: p["at"] for c, p in CHOKEPOINTS.items()}, **{r["id"]: r["hub"] for r in REGIONS}}

# Each lane runs from its first place to its second through the waypoints between them.
LANES = [
    ("east-asia", "malacca", [[122.3, 28.5], [120.3, 25], [117, 22.3], [112, 17], [109.8, 11.5], [107, 6], [104.5, 1.3], [103.5, 1.05], [101.5, 2.2]]),
    ("malacca", "ceylon", [[98, 5.7], [94, 6]]),
    ("ceylon", "aden", [[70, 9]]),
    ("south-asia", "aden", [[62, 15]]),
    ("south-asia", "ceylon", [[72.5, 12], [76.5, 7]]),
    ("aden", "bab", [[46, 12.4]]),
    ("bab", "red-sea", [[40, 16]]),
    ("red-sea", "suez", [[34.5, 26.5], [33.2, 28.3]]),
    ("suez", "mediterranean", [[32.3, 31.6], [28, 33], [20, 34.3], [15, 35.6]]),
    ("mediterranean", "gibraltar", [[9, 37.9], [5, 37.6], [0, 37.1], [-3, 36.1], [-4.8, 35.95]]),
    ("mediterranean", "turkish", [[16, 36.2], [22.5, 35.7], [24, 36.5], [25.3, 38.4], [25.9, 39.8], [26.6, 40.3], [27.6, 40.75]]),
    ("turkish", "black-sea", [[31.5, 43]]),
    ("gibraltar", "iberia", []),
    ("iberia", "ushant", [[-9.6, 37], [-9.8, 43.3]]),
    ("ushant", "north-sea", [[-1, 50.25], [1, 50.75], [1.5, 51.05], [2.2, 51.4]]),
    ("north-sea", "danish", [[4, 56], [8, 57.8], [10.9, 58.05], [11, 57.8], [11.6, 57]]),
    ("danish", "baltic", [[12.75, 55.75], [12.8, 55.5], [12.95, 55.15], [14.3, 54.8]]),
    ("iberia", "americas", [[-40, 38]]),
    ("iberia", "west-africa", [[-11, 30.6], [-14, 27.5], [-17.6, 21], [-18, 15], [-17.8, 12.5], [-13.5, 7], [-8, 4.1]]),
    ("iberia", "south-atlantic", [[-12.5, 31], [-19, 25], [-21, 15], [-30, 0], [-34.4, -8], [-39.5, -20], [-41, -23], [-43, -23.7]]),
    ("west-africa", "cape", [[3, 0], [8, -8], [10, -17], [13, -28]]),
    ("cape", "iberia", [[5, -20], [-10, 0], [-20, 15], [-20, 27]]),
    ("ceylon", "cape", [[65, -10], [50, -28], [35, -36]]),
    ("pacific-south-america", "south-atlantic", [[-80, -30], [-78, -50], [-67, -57.5], [-60, -55], [-55, -45], [-50, -35]]),
    ("cape", "east-africa", [[26, -35], [32, -31.5], [36, -25], [40.5, -18], [42, -11], [41, -6]]),
    ("east-africa", "aden", [[48.5, 3]]),
    ("oceania", "ceylon", [[150.8, -37.8], [146.5, -39.6], [140, -39.3], [115, -36], [105, -12]]),
    ("oceania", "east-asia", [[157, -15], [158, -5], [150, 5], [135, 15], [126, 26]]),
    ("east-asia", "panama", [[140, 33], [180, 38], [-140, 30], [-110, 15], [-85, 7], [-79.5, 8.7]]),
    ("antilles", "panama", [[-66, 15.5], [-75, 13], [-79.4, 10]]),
    ("antilles", "americas", [[-63, 25], [-68, 33]]),
    ("antilles", "iberia", [[-60, 21], [-40, 32]]),
    ("south-atlantic", "antilles", [[-43, -23.7], [-39.5, -20], [-34.4, -8], [-40, 0], [-55, 10], [-58, 15]]),
    ("pacific-south-america", "panama", [[-80.5, -8], [-82, -4.5], [-81.5, 0], [-79.5, 5.5], [-79.5, 8.7]]),
    ("pacific-south-america", "east-asia", [[-100, -10], [-150, 5], [170, 20], [140, 28]]),
    ("gulf", "hormuz", [[53, 26.2], [55.5, 26.4]]),
    ("hormuz", "aden", [[57.5, 25], [60.5, 22.6], [58.5, 17.5]]),
    ("hormuz", "south-asia", [[57.5, 25], [62, 23.5], [67, 21]]),
]

REGION_OF = {iso: r["id"] for r in REGIONS for iso in r["countries"].split()}


def distance(a, b):
    """Great-circle distance in kilometres."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


GRAPH = {}
for start, end, waypoints in LANES:
    line = [PLACES[start], *waypoints, PLACES[end]]
    length = sum(distance(a, b) for a, b in zip(line, line[1:]))
    GRAPH.setdefault(start, []).append((end, length, waypoints))
    GRAPH.setdefault(end, []).append((start, length, waypoints[::-1]))


def shortest(origin, destination, closed=()):
    """Length, places and drawn line of the shortest lane path between two places, None when closed places cut every path."""
    queue, seen = [(0, origin, [origin], [PLACES[origin]])], set(closed)
    while queue:
        length, place, places, line = heapq.heappop(queue)
        if place == destination:
            return length, places, line
        if place in seen:
            continue
        seen.add(place)
        for neighbour, step, waypoints in GRAPH[place]:
            if neighbour not in seen:
                heapq.heappush(queue, (length + step, neighbour, places + [neighbour], line + waypoints + [PLACES[neighbour]]))
    return None


@lru_cache
def plan(reporter_iso):
    """Every region's route to the reporter, or an empty list when the reporter has no region."""
    home = REGION_OF.get(reporter_iso)
    if home is None:
        return []
    routes = []
    for region in REGIONS:
        if region["id"] == home:
            via, path = [], None
        else:
            length, places, path = shortest(region["id"], home)
            via = [p for p in places if p in CHOKEPOINTS]
        routes.append({"id": region["id"], "name": region["name"], "via": via, "path": path, "km": length if path else 0})
    return routes


def route(reporter_iso, partner_iso):
    region = REGION_OF.get(partner_iso)
    return next((r for r in plan(reporter_iso) if r["id"] == region), None)


def by_route(suppliers):
    """Suppliers grouped by region id, None for a country with no region."""
    grouped = {}
    for s in suppliers:
        grouped.setdefault(REGION_OF.get(s.get("isoCode")), []).append(s)
    return grouped


def through(routes, chokepoint):
    return [r["id"] for r in routes if chokepoint in r["via"]]


# A container ship's usual 14 knots.
KM_PER_DAY = 14 * 1.852 * 24


@lru_cache
def detours(reporter_iso, closed):
    """For each route through a closed chokepoint, its next shortest lane or None when the closure cuts it off.

    closed is a sorted tuple of chokepoint ids.
    """
    home = REGION_OF.get(reporter_iso)
    found = {}
    for r in plan(reporter_iso):
        if not set(r["via"]) & set(closed):
            continue
        other = shortest(r["id"], home, closed)
        found[r["id"]] = other and {
            "path": other[2],
            "via": [p for p in other[1] if p in CHOKEPOINTS],
            "extraKm": other[0] - r["km"],
            "extraDays": (other[0] - r["km"]) / KM_PER_DAY,
        }
    return found
