import { t } from "./i18n.js";
import { chart, css, html, state } from "./lib.js";

const ATLAS = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json";
const ATLAS_SRI = "sha384-Aw4s9pX1PTPntIYkZ/qV9IYiF5Gv8eTl6Dd/TT56zfO1Wwd+owFwYUuuXNUMrWkc";
// BACI keeps a few pre-ISO country codes where world-atlas uses the current ISO 3166 numeric ones.
const ISO = { 251: 250, 490: 158, 579: 578, 699: 356, 757: 756, 842: 840 };
export const shapeId = (code) => String(ISO[code] ?? code).padStart(3, "0");

let world, shapes;
export function loadWorld() {
  world ??= fetch(ATLAS, { integrity: ATLAS_SRI })
    .then((r) => r.json())
    .then((topo) => {
      shapes = topojson.feature(topo, topo.objects.countries);
      shapes.features = shapes.features.filter((f) => f.properties.name !== "Antarctica");
      // Somaliland, Northern Cyprus and Kosovo carry no ISO id, so they keep their own name and match no supplier.
      for (const f of shapes.features) f.properties.name = f.id ?? f.properties.name;
      echarts.registerMap("world", shapes);
    });
  return world;
}

// The centre of a country's largest landmass, so overseas islands do not pull a flow line out to sea.
export function centroid(code) {
  const feature = shapes?.features.find((f) => f.properties.name === shapeId(code));
  if (!feature) return null;
  const polygons = feature.geometry.type === "Polygon" ? [feature.geometry.coordinates] : feature.geometry.coordinates;
  return d3.geoCentroid(polygons.map((coordinates) => ({ type: "Polygon", coordinates })).reduce((a, b) => (d3.geoArea(b) > d3.geoArea(a) ? b : a)));
}

// Asia and Oceania get a map centred on the Pacific, so their lanes cross an ocean instead of the map's edge.
const middle = (code) => ((centroid(code)?.[0] ?? 0) > 60 ? 150 : 0);

// Equal Earth keeps every country at its true area, which a shaded map needs, and d3 clips the land at the map's edge.
const projections = new Map();
function projection(center) {
  if (!projections.has(center)) {
    const p = d3.geoEqualEarth().rotate([-center, 0]);
    projections.set(center, { project: (point) => p(point), unproject: (point) => p.invert(point), stream: (s) => p.stream(s) });
  }
  return projections.get(center);
}

const EDGE = 179.95;
const along = (piece, [x1, y1]) => {
  const [x0, y0] = piece.at(-1);
  const steps = Math.max(1, Math.ceil(Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0)) / 4));
  for (let s = 1; s <= steps; s++) piece.push([x0 + ((x1 - x0) * s) / steps, y0 + ((y1 - y0) * s) / steps]);
};

// A lane is drawn straight between projected points, so each leg is bent into short steps and cut where it leaves one edge of the map for the other.
export function cut(coords, center) {
  // Clamped, so float noise cannot set a point past the edge it starts on.
  const rotated = coords.map(([lon, lat]) => [Math.max(-EDGE, Math.min(EDGE, ((((lon - center) % 360) + 540) % 360) - 180)), lat]);
  const pieces = [[rotated[0]]];
  for (let [x1, y1] of rotated.slice(1)) {
    const [x0, y0] = pieces.at(-1).at(-1);
    // Each leg takes the shorter way round, as a ship would.
    if (x1 - x0 > 180) x1 -= 360;
    else if (x0 - x1 > 180) x1 += 360;
    if (Math.abs(x1) > EDGE) {
      const edge = Math.sign(x1) * EDGE;
      const y = y0 + ((edge - x0) / (x1 - x0)) * (y1 - y0);
      along(pieces.at(-1), [edge, y]);
      pieces.push([[-edge, y]]);
      x1 -= Math.sign(x1) * 360;
    }
    along(pieces.at(-1), [x1, y1]);
  }
  return pieces.filter((p) => p.length > 1).map((p) => p.map(([x, y]) => [x + center, y]));
}

// Faint meridians and parallels over the sea, framed by the map's own edges.
function graticule(center) {
  const span = (from, to, at) => Array.from({ length: 41 }, (_, i) => at(from + ((to - from) * i) / 40));
  const [south, north] = [-56, 84];
  const line = (coords, edge) => ({ coords, lineStyle: edge ? { color: css("--border"), width: 0.8 } : undefined });
  return {
    id: "graticule", type: "lines", coordinateSystem: "geo", polyline: true, silent: true, z: -1,
    lineStyle: { color: css("--line"), width: 0.6 },
    data: [
      ...[-150, -120, -90, -60, -30, 0, 30, 60, 90, 120, 150].map((x) => line(span(south, north, (y) => [center + x, y]))),
      ...[-30, 0, 30, 60].map((y) => line(span(-EDGE, EDGE, (x) => [center + x, y]))),
      ...[-EDGE, EDGE].map((x) => line(span(south, north, (y) => [center + x, y]), true)),
      ...[south, north].map((y) => line(span(-EDGE, EDGE, (x) => [center + x, y]), true)),
    ],
  };
}

function prepare(option, center) {
  const { geo, visualMap, series } = option;
  const lanes = (s) => ({
    ...s,
    // A trail draws on its own canvas layer, which cannot repaint once a hidden map has shrunk it to nothing.
    ...(s.effect && { effect: { ...s.effect, trailLength: 0 } }),
    ...(s.polyline && s.data && { data: s.data.flatMap((d) => cut(d.coords, center).map((coords) => ({ ...d, coords }))) }),
  });
  return {
    ...option,
    ...(geo && { geo: {
      map: "world", projection: projection(center), roam: true, scaleLimit: { min: 1, max: 8 }, selectedMode: false,
      left: 0, right: 0, top: 8, bottom: visualMap ? 40 : 8,
      itemStyle: { areaColor: css("--land"), borderColor: css("--border"), borderWidth: 0.5 },
      emphasis: { label: { show: false }, itemStyle: { areaColor: css("--accent") } },
      ...geo,
    } }),
    ...(visualMap && { visualMap: { seriesIndex: 0, orient: "horizontal", left: "center", bottom: 4, itemWidth: 10, itemHeight: 140, textStyle: { color: css("--muted"), fontSize: 11 }, ...visualMap } }),
    // The graticule rides along last, so a series replace keeps it.
    ...(series && { series: [...series.map((s) => (s.type === "map" ? { geoIndex: 0, ...s } : s.type === "lines" ? lanes(s) : s)), graticule(center)] }),
  };
}

const centers = new WeakMap();

// Every map in the app: one projection, one look, lanes cut at the edge, and wheel, pinch, drag or buttons to move it.
export function worldMap(node, option) {
  const center = middle(state.reporter.countryCode);
  // The map moves at once on roam, so animated series would trail behind it.
  const instance = chart(node, { animationDurationUpdate: 0, ...prepare({ ...option, geo: option.geo ?? {}, series: option.series ?? [] }, center) });
  centers.set(instance, center);
  const at = (geo) => instance.setOption({ geo });
  const zoom = (by) => at({ zoom: Math.min(8, Math.max(1, (instance.getOption().geo[0].zoom ?? 1) * by)) });
  const controls = html(`<div class="zoom" role="group" aria-label="${t("Map controls")}">
    <button type="button" title="${t("Zoom in")}" aria-label="${t("Zoom in")}">+</button>
    <button type="button" title="${t("Zoom out")}" aria-label="${t("Zoom out")}">−</button>
    <button type="button">${t("Whole world")}</button></div>`).firstElementChild;
  const [zoomIn, zoomOut, reset] = controls.children;
  zoomIn.addEventListener("click", () => zoom(1.5));
  zoomOut.addEventListener("click", () => zoom(1 / 1.5));
  reset.addEventListener("click", () => at({ zoom: 1, center: null }));
  node.append(controls, html(`<a class="map-credit" href="https://www.naturalearthdata.com/" target="_blank" rel="noopener noreferrer">Natural Earth</a>`));
  return instance;
}

export const redraw = (instance, option, how) => instance.setOption(prepare(option, centers.get(instance)), how);
