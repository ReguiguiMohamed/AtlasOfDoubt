import { TABULATOR_LANGS, lang, t } from "./i18n.js";

export const state = { snapshots: [], snapshot: null, detail: null, reporter: null };

// BACI names countries in English. Other languages get the browser's own name for the alpha-2 code.
const regionNames = lang === "en" ? null : new Intl.DisplayNames(lang, { type: "region" });
let alpha2 = new Map();

function localize(value) {
  if (Array.isArray(value)) value.forEach(localize);
  else if (value && typeof value === "object") {
    const code = value.iso2 ?? alpha2.get(value.countryCode);
    // BACI gives defunct entities such as "Fed. Rep. of Germany (...1990)" the code of today's country, so they keep their own name.
    if (code && typeof value.countryName === "string" && !value.countryName.includes("(...")) value.countryName = regionNames.of(code);
    Object.values(value).forEach(localize);
  }
  return value;
}

export async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : body.detail?.[0]?.msg;
    throw Object.assign(new Error(detail ?? `${response.status} ${response.statusText}`), { status: response.status });
  }
  const body = await response.json();
  return regionNames ? localize(body) : body;
}

export const query = (params) =>
  new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")).toString();

export const scoped = (params = {}) => query({ snapshot: state.snapshot._id, reporter: state.reporter.countryCode, ...params });

export async function snapshotDetail() {
  if (state.detail?._id !== state.snapshot._id) {
    state.detail = await api(`/snapshots/${state.snapshot._id}`);
    alpha2 = new Map(state.detail.countries.map((c) => [c.countryCode, c.iso2]));
  }
  return state.detail;
}

const compactUsd = new Intl.NumberFormat(lang, { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 });
const fullUsd = new Intl.NumberFormat(lang, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const tonnes = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });
const percent = [0, 1, 2].map((d) => new Intl.NumberFormat(lang, { style: "percent", minimumFractionDigits: d, maximumFractionDigits: d }));
const hhi = new Intl.NumberFormat(lang, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const whole = new Intl.NumberFormat(lang);
const kilometres = new Intl.NumberFormat(lang, { style: "unit", unit: "kilometer", maximumFractionDigits: 0 });

export const usd = (v) => (v == null ? t("n/a") : compactUsd.format(v));
export const usdFull = (v) => (v == null ? t("n/a") : fullUsd.format(v));
export const pct = (v, digits = 1) => (v == null ? t("n/a") : percent[digits].format(v));
export const index = (v) => (v == null ? t("n/a") : hhi.format(v));
export const tons = (v) => (v == null ? t("n/a") : `${tonnes.format(v)} t`);
export const count = (v) => whole.format(v);
export const km = (v) => (v == null ? t("n/a") : kilometres.format(v));
const yesNo = (v) => (v == null ? t("n/a") : t(v ? "Yes" : "No"));

const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => entities[c]);

export function html(markup) {
  const template = document.createElement("template");
  template.innerHTML = markup.trim();
  return template.content;
}

export const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const charts = new Set();

export function chart(node, option) {
  const instance = echarts.init(node);
  instance.setOption({
    color: [css("--accent"), css("--warn"), css("--muted"), css("--accent-2")],
    textStyle: { fontFamily: css("--font"), color: css("--ink") },
    animationDuration: 300,
    ...option,
    // Unconfined, a tooltip near the chart edge spills past the page.
    tooltip: { confine: true, ...option.tooltip },
    ...(option.xAxis && interactive(option)),
  });
  if (option.xAxis) instance.getZr().on("dblclick", () => instance.dispatchAction({ type: "dataZoom", start: 0, end: 100 }));
  charts.add(instance);
  return instance;
}

const finePointer = matchMedia("(pointer: fine)").matches;

// Category axes zoom to fewer bars or years. Value axes zoom only where dots crowd, since a zoomed bar loses its base.
function interactive(option) {
  const series = option.series ?? [];
  const pick = (axes) => [axes].flat().flatMap((a, i) => (a.type === "category" || series.some((s) => s.type === "scatter") ? [i] : []));
  const x = pick(option.xAxis);
  const y = pick(option.yAxis);
  // A plain wheel or a finger drag still scrolls the page. Ctrl and the wheel zoom, a mouse drag pans.
  const inside = (key, index) => ({ type: "inside", [key]: index, filterMode: "none", zoomOnMouseWheel: "ctrl", moveOnMouseWheel: false, moveOnMouseMove: finePointer });
  return {
    grid: { ...option.grid, top: Math.max(option.grid?.top ?? 60, 30) },
    dataZoom: [...(x.length ? [inside("xAxisIndex", x)] : []), ...(y.length ? [inside("yAxisIndex", y)] : [])],
    toolbox: {
      right: 4, top: 0, itemSize: 14,
      iconStyle: { borderColor: css("--muted") },
      emphasis: { iconStyle: { borderColor: css("--accent") } },
      feature: {
        dataZoom: { xAxisIndex: x.length ? x : false, yAxisIndex: y.length ? y : false, filterMode: "none", title: { zoom: t("Zoom: drag a box, or Ctrl and the wheel"), back: t("Undo zoom") } },
        saveAsImage: { title: t("Save as image"), backgroundColor: css("--surface"), pixelRatio: 2 },
      },
    },
    // Hovering one series fades the others.
    series: series.map((s) => (series.length > 1 && s.type !== "lines" ? { emphasis: { focus: "series" }, ...s } : s)),
  };
}

export function disposeCharts() {
  charts.forEach((c) => c.dispose());
  charts.clear();
}

const resizeCharts = () => charts.forEach((c) => c.resize());
window.addEventListener("resize", resizeCharts);
// A printed page is narrower than the screen, and a canvas keeps the width it was drawn at.
matchMedia("print").addEventListener("change", resizeCharts);

export const axis = () => ({
  axisLine: { lineStyle: { color: css("--line") } },
  splitLine: { lineStyle: { color: css("--line") } },
  axisLabel: { color: css("--muted") },
});

export function table(node, options) {
  // Printing swaps in a plain table of every row, so a printed report is not cut to the page on screen.
  return new Tabulator(node, {
    layout: "fitColumns", pagination: true, paginationSize: 25, locale: lang, langs: TABULATOR_LANGS,
    printAsHtml: true, printRowRange: "all", ...options,
  });
}

// Tabulator guesses a sorter from the data and compares these as text, so 67.8M lands above 235M.
const numeric = (format) => (title, field, extra = {}) =>
  ({ title, field, hozAlign: "right", sorter: "number", formatter: (c) => format(c.getValue()), ...extra });
export const usdColumn = numeric(usd);
export const pctColumn = numeric(pct);
export const indexColumn = numeric(index);
export const tonsColumn = numeric(tons);

// GeoDist columns for a partner table, left out when the snapshot was prepared without GeoDist.
export const geoColumns = () => (state.snapshot.geography ? [
  numeric(km)(t("Distance"), "distanceKm", { width: 110 }),
  { title: t("Border"), field: "contiguous", width: 90, formatter: (c) => yesNo(c.getValue()) },
  { title: t("Language"), field: "commonLanguage", width: 100, formatter: (c) => yesNo(c.getValue()) },
] : []);

// Value-weighted mean distance over the partners GeoDist covers, and the share of all value that crosses a land border.
export function reach(rows) {
  const sum = (list) => list.reduce((a, r) => a + r.valueUsd, 0);
  const known = rows.filter((r) => r.distanceKm != null);
  const value = sum(known);
  if (!value) return null;
  return { km: known.reduce((a, r) => a + r.valueUsd * r.distanceKm, 0) / value, neighbours: sum(known.filter((r) => r.contiguous)) / sum(rows) };
}

const TIES = [["contiguous", "Shares a border", "--warn"], ["commonLanguage", "Shares an official language", "--accent"], [null, "Neither", "--muted"]];

// Trade against distance on log scales, the gravity pattern, with a least-squares line once there are enough partners to fit.
export function gravity(node, rows, pick) {
  const known = rows.filter((r) => r.distanceKm > 0 && r.valueUsd > 0);
  const xs = known.map((r) => Math.log(r.distanceKm));
  const ys = known.map((r) => Math.log(r.valueUsd));
  const mean = (v) => v.reduce((a, b) => a + b, 0) / v.length;
  const [mx, my] = [mean(xs), mean(ys)];
  const spread = xs.reduce((a, x) => a + (x - mx) ** 2, 0);
  const slope = known.length >= 8 && spread ? xs.reduce((a, x, i) => a + (x - mx) * (ys[i] - my), 0) / spread : null;
  const ends = [Math.min(...known.map((r) => r.distanceKm)), Math.max(...known.map((r) => r.distanceKm))];
  chart(node, {
    grid: { left: 70, right: 30, top: 40, bottom: 40 },
    legend: { textStyle: { color: css("--muted") } },
    tooltip: { formatter: (p) => (p.data.row ? `${esc(p.data.row.countryName)}: ${usd(p.data.row.valueUsd)}, ${km(p.data.row.distanceKm)}` : "") },
    xAxis: { ...axis(), type: "log", name: t("Distance"), nameLocation: "middle", nameGap: 26, axisLabel: { color: css("--muted"), formatter: km } },
    yAxis: { ...axis(), type: "log", axisLabel: { color: css("--muted"), formatter: usd } },
    series: [
      ...TIES.map(([field, name, color], i) => ({
        type: "scatter",
        name: t(name),
        itemStyle: { color: css(color), opacity: 0.8 },
        symbolSize: (_, p) => Math.max(6, Math.sqrt(p.data.row.share) * 70),
        data: known.filter((r) => TIES.findIndex(([f]) => !f || r[f]) === i).map((r) => ({ value: [r.distanceKm, r.valueUsd], row: r })),
      })),
      ...(slope == null ? [] : [{
        type: "line", name: t("Trend"), symbol: "none", silent: true, lineStyle: { type: "dashed", color: css("--ink") }, itemStyle: { color: css("--ink") },
        data: ends.map((d) => [d, Math.exp(my + slope * (Math.log(d) - mx))]),
      }]),
    ],
  }).on("click", (p) => p.data?.row && pick(p.data.row.countryCode));
  return slope;
}

// Along a log-log line, doubling the distance multiplies trade by 2 to the power of the slope.
export const doubling = (slope) => (slope == null ? "" : t("Along the trend, each doubling of distance goes with {change} trade. It describes this year's partners and is not a cause.", {
  change: t(slope < 0 ? "{share} less" : "{share} more", { share: pct(Math.abs(2 ** slope - 1), 0) }),
}));

// Tabulator's own header filter waits for keyup, so pasted or autofilled text never filtered.
export function countryPicker(node, countries, pick) {
  node.append(html(`<div class="controls"><label>${t("Search")} <input type="search" placeholder="${t("Filter countries")}" autofocus></label></div><div></div>`));
  const grid = table(node.lastElementChild, {
    data: countries,
    paginationSize: 20,
    initialSort: [{ column: "countryName", dir: "asc" }],
    columns: [
      { title: t("Country"), field: "countryName" },
      { title: t("ISO"), field: "isoCode", width: 90 },
    ],
  });
  grid.on("rowClick", (_, row) => pick(row.getData()));
  node.querySelector("input").addEventListener("input", (e) => {
    const term = e.target.value.trim().toLowerCase();
    grid.setFilter(term ? (c) => c.countryName.toLowerCase().includes(term) || c.isoCode?.toLowerCase() === term : []);
  });
}

export const kpi = (label, value, note = "") =>
  `<div class="kpi"><span class="label">${esc(label)}</span><strong>${esc(value)}</strong>${note && `<span class="note">${esc(note)}</span>`}</div>`;

// Wheel, pinch and drag move a map, and the buttons serve readers without a wheel.
export function zoomable(instance, component) {
  const at = (option) => instance.setOption({ [component]: [option] });
  const zoom = (by) => at({ zoom: Math.min(8, Math.max(1, (instance.getOption()[component][0].zoom ?? 1) * by)) });
  const controls = html(`<div class="zoom">
    <button type="button" title="${t("Zoom in")}" aria-label="${t("Zoom in")}">+</button>
    <button type="button" title="${t("Zoom out")}" aria-label="${t("Zoom out")}">−</button>
    <button type="button">${t("Whole world")}</button></div>`).firstElementChild;
  const [zoomIn, zoomOut, reset] = controls.children;
  zoomIn.addEventListener("click", () => zoom(1.5));
  zoomOut.addEventListener("click", () => zoom(1 / 1.5));
  reset.addEventListener("click", () => at({ zoom: 1, center: null }));
  at({ roam: true, scaleLimit: { min: 1, max: 8 } });
  // The map moves at once on roam, so animated series would trail behind it.
  instance.setOption({ animationDurationUpdate: 0 });
  instance.getDom().append(controls);
  return instance;
}

const ATLAS = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json";
const ATLAS_SRI = "sha384-yOCJ+8ShBm8UDqtAVtAvxTDDf4gXo5edxl/YG0FmVC5OTmqVLl7utuVGBDEeZWHf";
// BACI keeps a few pre-ISO country codes where world-atlas uses the current ISO 3166 numeric ones.
const ISO = { 251: 250, 490: 158, 579: 578, 699: 356, 757: 756, 842: 840 };
export const shapeId = (code) => String(ISO[code] ?? code).padStart(3, "0");

let world;
export function loadWorld() {
  world ??= fetch(ATLAS, { integrity: ATLAS_SRI })
    .then((r) => r.json())
    .then((topo) => {
      const shapes = topojson.feature(topo, topo.objects.countries);
      shapes.features = shapes.features.filter((f) => f.properties.name !== "Antarctica");
      // Somaliland, Northern Cyprus and Kosovo carry no ISO id, so they keep their own name and match no supplier.
      for (const f of shapes.features) {
        f.properties.name = f.id ?? f.properties.name;
        // Russia and Fiji have rings that cross the antimeridian and would draw a band across the whole map.
        const polygons = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
        for (const ring of polygons.flat()) {
          const xs = ring.map(([x]) => x);
          if (Math.max(...xs) - Math.min(...xs) > 180) for (const point of ring) if (point[0] < 0) point[0] += 360;
        }
      }
      echarts.registerMap("world", shapes);
    });
  return world;
}
