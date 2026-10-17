import { lang, t } from "../i18n.js";
import { api, axis, chart, count, css, doubling, esc, geoColumns, gravity, html, index, indexColumn, km, kpi, pct, pctColumn, query, reach, scoped, state, table, usd, usdColumn } from "../lib.js";

const THRESHOLDS = [0, 100_000, 1_000_000, 10_000_000, 100_000_000];
const BARS = 15;
const dollars = new Intl.NumberFormat(lang, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const expyValue = (e) => (e?.value == null ? null : Number(e.value));

export default async function exports(root, _, params) {
  const minValue = Number(params.get("minValue") ?? 1_000_000);
  const data = await api(`/exports?${scoped({ year: params.get("year"), minValue })}`);
  const reporter = esc(state.reporter.countryName);
  const current = data.years.find((y) => y.year === data.year);
  const shown = data.destinations.slice(0, BARS);
  const years = data.years.map((y) => String(y.year));
  const far = state.snapshot.geography && reach(data.destinations);

  root.append(html(`
    <div class="head">
      <h1>${t("Exports of {reporter}, {year}", { reporter, year: data.year })}</h1>
      <p class="lede">${t("Where the exports of {reporter} go, how concentrated they are by product and by destination, and how sophisticated the basket is by the income of the countries that export the same goods.", { reporter })}</p>
      <form class="controls">
        <label>${t("Year")} <select name="year">${state.snapshot.years
          .map((y) => `<option ${y === data.year ? "selected" : ""}>${y}</option>`).reverse().join("")}</select></label>
        <label>${t("Minimum export value")} <select name="minValue">${THRESHOLDS
          .map((v) => `<option value="${v}" ${v === minValue ? "selected" : ""}>${v ? t("{value} or more", { value: usd(v) }) : t("Any")}</option>`)
          .join("")}</select></label>
      </form>
    </div>
    <div class="kpis">
      ${kpi(t("Exports"), usd(current?.exportsUsd), String(data.year))}
      ${kpi(t("Destinations"), count(data.destinations.length))}
      ${kpi(t("Product HHI"), index(current?.productHhi))}
      ${kpi(t("Destination HHI"), index(current?.geoHhi))}
      ${kpi(t("EXPY"), expyValue(current?.expy) == null ? t("n/a") : dollars.format(expyValue(current.expy)), t("GDP per capita, PPP"))}
      ${far ? kpi(t("Average distance"), km(far.km), t("{share} to neighbours", { share: pct(far.neighbours) })) : ""}
    </div>
    <div class="panel"><h2>${t("Exports and concentration, {from} to {to}", { from: years[0], to: years.at(-1) })}</h2>
      <p>${t("The HHI runs from 0 to 1, where 1 means a single product or a single destination.")}</p>
      <div class="chart" id="trend"></div></div>
    ${data.gdp ? `<div class="panel"><h2>${t("Export sophistication, {from} to {to}", { from: years[0], to: years.at(-1) })}</h2>
      <p>${t("EXPY weights each product by PRODY, the income per head of the countries that export it, in constant PPP dollars. The fixed line keeps the 2012 PRODY, so it moves only when the basket changes. A year shows no value when a product in the basket lacks a PRODY.")}</p>
      <div class="chart" id="expy"></div></div>` : ""}
    <div class="grid">
      <div class="panel"><h2>${t("Destinations, {year}", { year: data.year })}</h2><div class="chart tall" id="bars"></div></div>
      <div class="panel"><h2>${t("Destination table")}</h2><div id="destinations"></div></div>
    </div>
    ${far ? `<div class="panel" style="margin-top:1.25rem"><h2>${t("Distance and value, {year}", { year: data.year })}</h2>
      <p>${t("Each bubble is a destination, sized by its share, on log scales. Neighbours and partners sharing an official language stand out.")} <span id="doubling"></span></p>
      <div class="chart tall" id="gravity"></div></div>` : ""}
    <div class="panel" style="margin-top:1.25rem"><h2>${data.products.length === 1 ? t("1 product") : t("{count} products", { count: count(data.products.length) })}</h2>
      <p>${t("RCA above 1 means {reporter} exports relatively more of the product than the world does. The unit value is only read as a price when no quality flag is raised.", { reporter })}</p>
      <div id="products"></div></div>
  `));

  const form = root.querySelector("form");
  form.addEventListener("change", () => (location.hash = `#/exports?${query({ year: form.year.value, minValue: form.minValue.value })}`));

  chart(root.querySelector("#trend"), {
    grid: { left: 70, right: 60, top: 40, bottom: 30 },
    legend: { textStyle: { color: css("--muted") } },
    tooltip: { trigger: "axis" },
    xAxis: { ...axis(), type: "category", data: years },
    yAxis: [
      { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
      { ...axis(), type: "value", min: 0, max: 1, splitLine: { show: false } },
    ],
    series: [
      { name: t("Exports"), type: "bar", data: data.years.map((y) => y.exportsUsd), itemStyle: { color: css("--accent") }, tooltip: { valueFormatter: usd } },
      { name: t("Imports"), type: "bar", data: data.years.map((y) => y.importsUsd ?? null), itemStyle: { color: css("--accent-2") }, tooltip: { valueFormatter: usd } },
      { name: t("Product HHI"), type: "line", yAxisIndex: 1, data: data.years.map((y) => y.productHhi ?? null), itemStyle: { color: css("--warn") }, tooltip: { valueFormatter: index } },
      { name: t("Destination HHI"), type: "line", yAxisIndex: 1, lineStyle: { type: "dashed" }, data: data.years.map((y) => y.geoHhi ?? null), itemStyle: { color: css("--muted") }, tooltip: { valueFormatter: index } },
    ],
  });

  if (data.gdp) {
    chart(root.querySelector("#expy"), {
      grid: { left: 80, right: 30, top: 40, bottom: 30 },
      legend: { textStyle: { color: css("--muted") } },
      tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? t("n/a") : dollars.format(v)) },
      xAxis: { ...axis(), type: "category", data: years },
      yAxis: { ...axis(), type: "value", scale: true, axisLabel: { color: css("--muted"), formatter: usd } },
      series: [
        { name: t("EXPY"), type: "line", data: data.years.map((y) => expyValue(y.expy)), itemStyle: { color: css("--accent") } },
        { name: t("EXPY at 2012 PRODY"), type: "line", lineStyle: { type: "dashed" }, data: data.years.map((y) => expyValue(y.expyFixed2012)), itemStyle: { color: css("--warn") } },
      ],
    });
  }

  const profile = (code) => code && (location.hash = `#/country/${code}?year=${data.year}`);
  chart(root.querySelector("#bars"), {
    grid: { left: 140, right: 70, top: 10, bottom: 30 },
    tooltip: { formatter: (p) => `${esc(p.name)}: ${usd(p.value)} (${pct(shown[p.dataIndex].share)})` },
    xAxis: { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
    yAxis: { type: "category", inverse: true, data: shown.map((d) => d.countryName), axisLabel: { color: css("--ink") } },
    series: [{
      type: "bar",
      barMaxWidth: 28,
      data: shown.map((d) => d.valueUsd),
      label: { show: true, position: "right", color: css("--muted"), formatter: (p) => pct(shown[p.dataIndex].share) },
    }],
  }).on("click", (p) => profile(shown[p.dataIndex].countryCode));

  if (far) root.querySelector("#doubling").textContent = doubling(gravity(root.querySelector("#gravity"), data.destinations, profile));

  table(root.querySelector("#destinations"), {
    data: data.destinations,
    paginationSize: 12,
    columns: [
      { title: t("Country"), field: "countryName", minWidth: 140 },
      { title: t("ISO"), field: "isoCode", width: 70 },
      usdColumn(t("Exports"), "valueUsd"),
      pctColumn(t("Share"), "share"),
      ...geoColumns(),
    ],
  }).on("rowClick", (_, row) => profile(row.getData().countryCode));

  table(root.querySelector("#products"), {
    data: data.products,
    initialSort: [{ column: "totalUsd", dir: "desc" }],
    columns: [
      { title: t("Code"), field: "productCode", width: 90 },
      { title: t("Product"), field: "description", minWidth: 220, tooltip: true },
      usdColumn(t("Exports"), "totalUsd", { width: 120 }),
      pctColumn(t("World share"), "worldShare", { width: 120 }),
      indexColumn(t("RCA"), "rca", { width: 80 }),
      usdColumn(t("Unit value per tonne"), "unitValueUsdPerTonne", { width: 160 }),
      { title: t("Quality flags"), field: "qualityFlags", headerSort: false, minWidth: 160, formatter: (c) => esc(c.getValue().map((f) => t(f)).join(", ")) },
    ],
  }).on("rowClick", (_, row) => (location.hash = `#/product/${row.getData().productCode}?year=${data.year}`));
}
