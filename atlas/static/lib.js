import { TABULATOR_LANGS, lang, t } from "./i18n.js";

export const state = { snapshots: [], snapshot: null, detail: null };

// BACI names countries in English. Other languages get the browser's own name for the alpha-2 code.
const regionNames = lang === "en" ? null : new Intl.DisplayNames(lang, { type: "region" });
let alpha2 = new Map();

function localize(value) {
  if (Array.isArray(value)) value.forEach(localize);
  else if (value && typeof value === "object") {
    const code = value.iso2 ?? alpha2.get(value.countryCode);
    if (code && typeof value.countryName === "string") value.countryName = regionNames.of(code);
    Object.values(value).forEach(localize);
  }
  return value;
}

export async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : body.detail?.[0]?.msg;
    throw new Error(detail ?? `${response.status} ${response.statusText}`);
  }
  const body = await response.json();
  return regionNames ? localize(body) : body;
}

export const query = (params) =>
  new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")).toString();

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

export const usd = (v) => (v == null ? t("n/a") : compactUsd.format(v));
export const usdFull = (v) => (v == null ? t("n/a") : fullUsd.format(v));
export const pct = (v, digits = 1) => (v == null ? t("n/a") : percent[digits].format(v));
export const index = (v) => (v == null ? t("n/a") : hhi.format(v));
export const tons = (v) => (v == null ? t("n/a") : `${tonnes.format(v)} t`);
export const count = (v) => whole.format(v);

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
  });
  charts.add(instance);
  return instance;
}

export function disposeCharts() {
  charts.forEach((c) => c.dispose());
  charts.clear();
}

window.addEventListener("resize", () => charts.forEach((c) => c.resize()));

export const axis = () => ({
  axisLine: { lineStyle: { color: css("--line") } },
  splitLine: { lineStyle: { color: css("--line") } },
  axisLabel: { color: css("--muted") },
});

export function table(node, options) {
  return new Tabulator(node, { layout: "fitColumns", pagination: true, paginationSize: 25, locale: lang, langs: TABULATOR_LANGS, ...options });
}

// Tabulator guesses a sorter from the data and compares these as text, so 67.8M lands above 235M.
const numeric = (format) => (title, field, extra = {}) =>
  ({ title, field, hozAlign: "right", sorter: "number", formatter: (c) => format(c.getValue()), ...extra });
export const usdColumn = numeric(usd);
export const pctColumn = numeric(pct);
export const indexColumn = numeric(index);
export const tonsColumn = numeric(tons);

export const kpi = (label, value, note = "") =>
  `<div class="kpi"><span class="label">${esc(label)}</span><strong>${esc(value)}</strong>${note && `<span class="note">${esc(note)}</span>`}</div>`;
