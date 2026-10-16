"""Modelled sea routes from each supplier country to Tunisia.

BACI records who sold what, not how it travelled. Each country is assigned
the shortest usual sea lane to Tunis and the chokepoints on it, so the value
behind a strait is an estimate of exposure, not a shipping record.
Mediterranean and overland neighbours pass no chokepoint. Coordinates are
[longitude, latitude], and each path ends in Tunis so the map can draw it.
Waypoints stay at sea on the 1:110m world map the app draws, which closes
the narrowest straits, so a few sit where that map still shows water.
"""

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

TUNIS = [10.35, 36.85]
_C = {k: v["at"] for k, v in CHOKEPOINTS.items()}
RED_SEA = [_C["bab"], [40, 16], [37.5, 21], [34.5, 26.5], [33.2, 28.3], _C["suez"], [32.3, 31.6], [28, 33], [20, 34.3], [15, 35.6], [11.5, 37.4], TUNIS]
WEST_MED = [_C["gibraltar"], [-4.8, 35.95], [-3, 36.1], [0, 37.1], [5, 37.6], [9, 37.9], [11, 37.4], TUNIS]
ATLANTIC_EUROPE = [[1.5, 51.05], [1, 50.75], [-1, 50.25], [-5.8, 48.6], [-9.8, 43.3], [-9.6, 37], *WEST_MED]
GULF_OF_ADEN = [[52.2, 12.4], [46, 12.4], *RED_SEA]

ROUTES = [
    {
        "id": "east-asia",
        "name": "East and Southeast Asia",
        "via": ["malacca", "bab", "suez"],
        "path": [
            [123, 30.5], [122.3, 28.5], [120.3, 25], [117, 22.3], [112, 17], [109.8, 11.5], [107, 6], [104.5, 1.3],
            [103.5, 1.05], [101.5, 2.2], _C["malacca"], [98, 5.7], [94, 6], [80.6, 5.3], [70, 9], *GULF_OF_ADEN,
        ],
        "countries": "CHN HKG MAC S19 JPN KOR PRK MNG VNM THA KHM LAO PHL IDN MYS SGP BRN TLS",
    },
    {
        "id": "south-asia",
        "name": "South Asia",
        "via": ["bab", "suez"],
        "path": [[72.6, 18.8], [62, 15], *GULF_OF_ADEN],
        "countries": "IND PAK BGD LKA NPL BTN MDV MMR AFG",
    },
    {
        "id": "oceania",
        "name": "Oceania",
        "via": ["bab", "suez"],
        "path": [[151.6, -34], [150.8, -37.8], [146.5, -39.6], [140, -39.3], [115, -36], [105, -12], [80.6, 5], [70, 9], *GULF_OF_ADEN],
        "countries": "AUS NZL PNG FJI SLB VUT NCL PYF WSM TON KIR TUV NRU FSM MHL PLW GUM MNP ASM COK NIU TKL WLF PCN NFK CXR CCK PUS",
    },
    {
        "id": "gulf",
        "name": "Persian Gulf",
        "via": ["hormuz", "bab", "suez"],
        "path": [[50.5, 27.5], [53, 26.2], [55.5, 26.4], _C["hormuz"], [57.5, 25], [60.5, 22.6], [58.5, 17.5], *GULF_OF_ADEN],
        "countries": "SAU ARE QAT KWT BHR IRQ IRN",
    },
    {
        "id": "east-africa",
        "name": "Arabian Sea and East Africa",
        "via": ["bab", "suez"],
        "path": [[40, -4.2], [48.5, 3], *GULF_OF_ADEN],
        "countries": "OMN YEM DJI ETH SOM KEN TZA MOZ MDG MUS SYC COM MYT UGA RWA BDI ZMB MWI ZWE SSD",
    },
    {
        "id": "red-sea",
        "name": "Red Sea",
        "via": ["suez"],
        "path": [[38.6, 21.5], [34.5, 26.5], *RED_SEA[4:]],
        "countries": "JOR SDN ERI",
    },
    {
        "id": "black-sea",
        "name": "Black Sea and Central Asia",
        "via": ["turkish"],
        "path": [
            [37.6, 44.6], [31.5, 43], _C["turkish"], [27.6, 40.75], [26.6, 40.3], [25.9, 39.8], [25.3, 38.4], [24, 36.5],
            [22.5, 35.7], [16, 36.2], [11.5, 37.4], TUNIS,
        ],
        "countries": "RUS UKR ROU BGR GEO MDA KAZ BLR ARM UZB TKM KGZ TJK",
    },
    {
        "id": "baltic",
        "name": "Baltic",
        "via": ["danish", "gibraltar"],
        "path": [
            [18.8, 55], [14.3, 54.8], [12.95, 55.15], [12.8, 55.5], [12.75, 55.75], _C["danish"], [11.6, 57], [11, 57.8],
            [10.9, 58.05], [8, 57.8], [4, 56], [2.2, 51.4], *ATLANTIC_EUROPE,
        ],
        "countries": "SWE FIN EST LVA LTU POL",
    },
    {
        "id": "north-sea",
        "name": "North Sea and Atlantic Europe",
        "via": ["gibraltar"],
        "path": [[3.7, 52.2], [2.2, 51.4], *ATLANTIC_EUROPE],
        "countries": "GBR IRL NLD BEL DEU DNK NOR ISL PRT",
    },
    {
        "id": "americas",
        "name": "North and Central America and the Caribbean",
        "via": ["gibraltar"],
        "path": [[-73.5, 40.3], [-40, 38], [-9.9, 36.6], *WEST_MED],
        "countries": (
            "USA CAN MEX CUB DOM HTI JAM TTO BHS BRB ATG DMA GRD KNA LCA VCT ABW CUW BES SXM ANT BLM AIA VGB CYM "
            "TCA MSR BMU GTM HND SLV NIC CRI PAN BLZ VEN COL GUY SUR GRL SPM"
        ),
    },
    {
        "id": "south-atlantic",
        "name": "South America, Atlantic coast",
        "via": ["gibraltar"],
        "path": [
            [-46, -24.4], [-43, -23.7], [-41, -23], [-39.5, -20], [-34.4, -8], [-30, 0], [-21, 15], [-19, 25], [-12.5, 31],
            [-9.9, 35.6], *WEST_MED,
        ],
        "countries": "BRA ARG URY PRY FLK",
    },
    {
        "id": "west-africa",
        "name": "West and Southern Africa",
        "via": ["gibraltar"],
        "path": [
            [-4, 4.9], [-8, 4.1], [-13.5, 7], [-17.8, 12.5], [-18, 15], [-17.6, 21], [-14, 27.5], [-11, 30.6], [-9.9, 35.6],
            *WEST_MED,
        ],
        "countries": (
            "SEN CIV GHA NGA CMR GAB COG COD AGO NAM ZAF ZA1 MRT GIN SLE LBR TGO BEN GNQ GMB GNB CPV STP MLI BFA NER "
            "TCD CAF BWA LSO SWZ SHN"
        ),
    },
    {
        "id": "pacific-south-america",
        "name": "South America, Pacific coast",
        "via": ["panama", "gibraltar"],
        "path": [
            [-77.6, -12.1], [-80.5, -8], [-82, -4.5], [-81.5, 0], [-79.5, 5.5], [-79.5, 8.7], _C["panama"], [-79.4, 10],
            [-75, 13], [-66, 15.5], [-63, 18.8], [-60, 21], [-40, 32], [-9.9, 36], *WEST_MED,
        ],
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
