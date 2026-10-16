"""Modelled sea routes from each supplier country to Tunisia.

BACI records who sold what, not how it travelled. Each country is assigned
the shortest usual sea lane to Tunis and the chokepoints on it, so the value
behind a strait is an estimate of exposure, not a shipping record.
Mediterranean and overland neighbours pass no chokepoint. Coordinates are
[longitude, latitude], and each path ends in Tunis so the map can draw it.
"""

CHOKEPOINTS = {
    "gibraltar": {"name": "Strait of Gibraltar", "at": [-5.6, 35.95]},
    "suez": {"name": "Suez Canal", "at": [32.35, 30.55]},
    "bab": {"name": "Bab el-Mandeb", "at": [43.35, 12.6]},
    "hormuz": {"name": "Strait of Hormuz", "at": [56.45, 26.55]},
    "malacca": {"name": "Strait of Malacca", "at": [100.9, 2.6]},
    "turkish": {"name": "Turkish Straits", "at": [29.05, 41.1]},
    "danish": {"name": "Danish Straits", "at": [12.7, 55.95]},
    "panama": {"name": "Panama Canal", "at": [-79.7, 9.15]},
}

TUNIS = [10.35, 36.85]
_C = {k: v["at"] for k, v in CHOKEPOINTS.items()}
RED_SEA = [_C["bab"], [38, 20], [33.5, 28], _C["suez"], [32.3, 31.4], [25, 34], [15, 35.5], [11.2, 37.25], TUNIS]
WEST_MED = [_C["gibraltar"], [0, 37], [8.5, 37.7], [10.6, 37.2], TUNIS]
ATLANTIC_EUROPE = [[-5, 48.5], [-10, 43], [-9.8, 37], *WEST_MED]

ROUTES = [
    {
        "id": "east-asia",
        "name": "East and Southeast Asia",
        "via": ["malacca", "bab", "suez"],
        "path": [[122, 30.5], [114, 21], [104.2, 1.3], _C["malacca"], [97, 5.8], [80.6, 5.6], [50, 12.3], *RED_SEA],
        "countries": "CHN HKG MAC S19 JPN KOR PRK MNG VNM THA KHM LAO PHL IDN MYS SGP BRN TLS",
    },
    {
        "id": "south-asia",
        "name": "South Asia",
        "via": ["bab", "suez"],
        "path": [[72.8, 18.9], [60, 14], [50, 12.3], *RED_SEA],
        "countries": "IND PAK BGD LKA NPL BTN MDV MMR AFG",
    },
    {
        "id": "oceania",
        "name": "Oceania",
        "via": ["bab", "suez"],
        "path": [[151.3, -33.9], [146, -40], [115, -36], [105, -12], [80.6, 5], [50, 12.3], *RED_SEA],
        "countries": "AUS NZL PNG FJI SLB VUT NCL PYF WSM TON KIR TUV NRU FSM MHL PLW GUM MNP ASM COK NIU TKL WLF PCN NFK CXR CCK PUS",
    },
    {
        "id": "gulf",
        "name": "Persian Gulf",
        "via": ["hormuz", "bab", "suez"],
        "path": [[50.5, 27.5], [54, 26.3], _C["hormuz"], [57.5, 25], [59.8, 22.5], [58, 17], [50, 12.3], *RED_SEA],
        "countries": "SAU ARE QAT KWT BHR IRQ IRN",
    },
    {
        "id": "east-africa",
        "name": "Arabian Sea and East Africa",
        "via": ["bab", "suez"],
        "path": [[39.7, -4.1], [48, 3], [52, 12.3], [45, 12], *RED_SEA],
        "countries": "OMN YEM DJI ETH SOM KEN TZA MOZ MDG MUS SYC COM MYT UGA RWA BDI ZMB MWI ZWE SSD",
    },
    {
        "id": "red-sea",
        "name": "Red Sea",
        "via": ["suez"],
        "path": [[38.5, 21.5], [33.8, 27.8], *RED_SEA[3:]],
        "countries": "JOR SDN ERI",
    },
    {
        "id": "black-sea",
        "name": "Black Sea and Central Asia",
        "via": ["turkish"],
        "path": [[37.8, 44.7], [31.5, 43], _C["turkish"], [26.4, 40.1], [25.5, 38.5], [23, 36], [16, 36.3], [11.2, 37.25], TUNIS],
        "countries": "RUS UKR ROU BGR GEO MDA KAZ BLR ARM UZB TKM KGZ TJK",
    },
    {
        "id": "baltic",
        "name": "Baltic",
        "via": ["danish", "gibraltar"],
        "path": [[18.7, 54.6], [14, 55.3], _C["danish"], [11.8, 57.3], [9.5, 57.9], [4, 56], [1.5, 51], *ATLANTIC_EUROPE],
        "countries": "SWE FIN EST LVA LTU POL",
    },
    {
        "id": "north-sea",
        "name": "North Sea and Atlantic Europe",
        "via": ["gibraltar"],
        "path": [[4, 52], [1.5, 51], *ATLANTIC_EUROPE],
        "countries": "GBR IRL NLD BEL DEU DNK NOR ISL PRT",
    },
    {
        "id": "americas",
        "name": "North and Central America and the Caribbean",
        "via": ["gibraltar"],
        "path": [[-74, 40.5], [-40, 38], [-9.8, 36.5], *WEST_MED],
        "countries": (
            "USA CAN MEX CUB DOM HTI JAM TTO BHS BRB ATG DMA GRD KNA LCA VCT ABW CUW BES SXM ANT BLM AIA VGB CYM "
            "TCA MSR BMU GTM HND SLV NIC CRI PAN BLZ VEN COL GUY SUR GRL SPM"
        ),
    },
    {
        "id": "south-atlantic",
        "name": "South America, Atlantic coast",
        "via": ["gibraltar"],
        "path": [[-46.3, -24], [-34.5, -7], [-20, 15], [-12, 30], [-9.5, 35.8], *WEST_MED],
        "countries": "BRA ARG URY PRY FLK",
    },
    {
        "id": "west-africa",
        "name": "West and Southern Africa",
        "via": ["gibraltar"],
        "path": [[-4, 5], [-17.5, 14.7], [-17, 21], [-11, 30], [-9.5, 35.8], *WEST_MED],
        "countries": (
            "SEN CIV GHA NGA CMR GAB COG COD AGO NAM ZAF ZA1 MRT GIN SLE LBR TGO BEN GNQ GMB GNB CPV STP MLI BFA NER "
            "TCD CAF BWA LSO SWZ SHN"
        ),
    },
    {
        "id": "pacific-south-america",
        "name": "South America, Pacific coast",
        "via": ["panama", "gibraltar"],
        "path": [[-77.2, -12], [-82, -2], [-79.5, 8.8], _C["panama"], [-75, 13], [-68, 18.2], [-60, 21], [-40, 32], [-9.8, 36], *WEST_MED],
        "countries": "CHL PER ECU BOL",
    },
    {
        "id": "direct",
        "name": "Mediterranean and overland",
        "via": [],
        "path": None,
        "countries": (
            "ITA FRA ESP GRC MLT CYP TUR LBY DZA MAR EGY ISR LBN SYR PSE SVN HRV ALB MNE BIH SRB MKD MCO SMR AND "
            "AUT CHE HUN CZE SVK LUX LIE AZE GIB"
        ),
    },
]

ROUTE_OF = {iso: route["id"] for route in ROUTES for iso in route["countries"].split()}


def by_route(suppliers):
    """Suppliers grouped by route id, under None when no route covers the country."""
    groups = {}
    for s in suppliers:
        groups.setdefault(ROUTE_OF.get(s.get("isoCode")), []).append(s)
    return groups


def through(chokepoint):
    return [r["id"] for r in ROUTES if chokepoint in r["via"]]
