import { t } from "../i18n.js";
import { api, axis, chart, count, css, esc, geoColumns, html, index, kpi, loadWorld, pct, pctColumn, query, scoped, shapeId, state, table, tonsColumn, usd, usdColumn, zoomable } from "../lib.js";

const CASE_STUDIES = [
  ["10", "Cereals (chapter 10)"],
  ["1001", "Wheat and meslin"],
  ["31", "Fertilisers (chapter 31)"],
  ["85", "Electrical machinery and equipment (chapter 85)"],
];
const BARS = 15;
const TRACKED = 5;

export default async function product(root, [code], params) {
  if (!code) return search(root, params.get("q") ?? "");
  const data = await api(`/products/${code}/history?${scoped()}`);
  const reporter = esc(state.reporter.countryName);
  const single = code.length === 6;
  const members = data.products.length;
  const title = single
    ? data.products[0].description
    : `${t(code.length === 2 ? "Chapter" : "Heading")}, ${members === 1 ? t("1 product") : t("{count} products", { count: count(members) })}`;
  const recorded = data.years.filter((y) => y.metrics);
  if (!recorded.length) {
    root.append(html(`<div class="head"><h1><span class="code">${esc(code)}</span> ${esc(title)}</h1>
      <p class="notice">${t("BACI records no imports of this code into {reporter} between {from} and {to}.", { reporter, from: state.snapshot.years[0], to: state.snapshot.years.at(-1) })}</p></div>`));
    return;
  }
  const wanted = Number(params.get("year"));
  const current = recorded.find((y) => y.year === wanted) ?? recorded.at(-1);
  const m = current.metrics;

  root.append(html(`
    <div class="head">
      <h1><span class="code">${esc(code)}</span> ${esc(title)}</h1>
      <p class="lede">${t(single ? "HS6 product {code}, in heading {heading} of chapter {chapter}." : "Every HS6 product whose code starts with {code}. Supplier values are summed across the group before shares and the HHI are computed.", { code, heading: code.slice(0, 4), chapter: code.slice(0, 2) })}
        ${t("Gaps in the trend are years with no recorded flow into {reporter}.", { reporter })}</p>
      <form class="controls">
        <label>${t("Year")} <select name="year">${recorded
          .map((y) => `<option ${y.year === current.year ? "selected" : ""}>${y.year}</option>`).reverse().join("")}</select></label>
        <a href="#/scenario?${query({ mode: "product", code, year: current.year })}"><button type="button" class="primary">${t("Run a disruption scenario")}</button></a>
        <a href="#/routes?${query({ code, year: current.year })}">${t("Sea routes")}</a>
      </form>
    </div>
    <div class="kpis">
      ${kpi(t("Imports"), usd(m.totalUsd), String(current.year))}
      ${kpi(t("Suppliers"), m.supplierCount)}
      ${kpi(t("Largest supplier"), pct(m.topSupplier.share), m.topSupplier.countryName)}
      ${kpi(t("Top 3 share"), pct(m.top3Share))}
      ${kpi(t("HHI"), index(m.hhi), m.hhi >= 0.25 ? t("highly concentrated") : "")}
      ${current.world ? kpi(t("World exporter HHI"), index(current.world.hhi), t("{name} leads world exports", { name: current.world.topSupplier?.countryName })) : ""}
    </div>
    <div class="panel" id="where"><h2>${t("Where the supply comes from, {year}", { year: current.year })}</h2>
      <p>${t("Shaded by share of the imports of {reporter}, with {reporter} in red. Very small countries do not show at this scale and are listed in the table.", { reporter })}</p>
      <div class="chart map" id="map"></div></div>
    <div class="grid">
      <div class="panel"><h2>${t("Suppliers in {year}", { year: current.year })}</h2><div class="chart tall" id="bars"></div></div>
      <div class="panel"><h2>${t("Supplier table")}</h2><div id="suppliers"></div></div>
    </div>
    <div class="panel" style="margin-top:1.25rem"><h2>${t("Imports and concentration, {from} to {to}", { from: data.years[0].year, to: data.years.at(-1).year })}</h2>
      <div class="chart" id="trend"></div></div>
    <div class="panel"><h2>${t("Shares of the five largest suppliers over time")}</h2><div class="chart" id="shares"></div></div>
    <div class="panel"><h2>${t("Exports of {reporter}, {from} to {to}", { reporter, from: data.years[0].year, to: data.years.at(-1).year })}</h2>
      <p>${t("Revealed comparative advantage compares the share of this code in the exports of {reporter} with its share in world exports. Above 1, {reporter} exports relatively more of it than the world does.", { reporter })}</p>
      <div class="chart" id="exports"></div></div>
    ${current.world ? `<div class="panel"><h2>${t("Who else sells it, {year}", { year: current.year })}</h2>
      <p>${t("The largest exporters of this product worldwide, against what each sent {reporter}. A large exporter that sends little is a supplier {reporter} could turn to.", { reporter })}</p>
      <div id="exporters"></div></div>` : ""}
    ${single ? "" : `<div class="panel"><h2>${t("Products in this group")}</h2><div id="members"></div></div>`}
  `));
  if (m.hhi >= 0.25) root.querySelector(".kpis .kpi:nth-child(5)").classList.add("alert");

  root.querySelector("select[name=year]").addEventListener("change", (e) => {
    location.hash = `#/product/${code}?year=${e.target.value}`;
  });

  const ranked = current.suppliers;
  const shown = ranked.slice(0, BARS);
  const rest = ranked.slice(BARS);
  if (rest.length) {
    shown.push({ countryName: t("{count} others", { count: rest.length }), valueUsd: rest.reduce((a, s) => a + s.valueUsd, 0), share: rest.reduce((a, s) => a + s.share, 0) });
  }
  const profile = (countryCode) => countryCode && (location.hash = `#/country/${countryCode}?year=${current.year}`);
  const bars = chart(root.querySelector("#bars"), {
    grid: { left: 140, right: 70, top: 10, bottom: 30 },
    tooltip: { formatter: (p) => `${esc(p.name)}: ${usd(p.value)} (${pct(shown[p.dataIndex].share)})` },
    xAxis: { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
    yAxis: { type: "category", inverse: true, data: shown.map((s) => s.countryName), axisLabel: { color: css("--ink") } },
    series: [{
      type: "bar",
      barMaxWidth: 28,
      data: shown.map((s) => s.valueUsd),
      label: { show: true, position: "right", color: css("--muted"), formatter: (p) => pct(shown[p.dataIndex].share) },
    }],
  });
  bars.on("click", (p) => profile(shown[p.dataIndex].countryCode));

  const suppliers = table(root.querySelector("#suppliers"), {
    data: ranked.map((s) => ({ ...s, ...data.geography[s.countryCode] })),
    paginationSize: 12,
    columns: [
      { title: t("Country"), field: "countryName", minWidth: 140 },
      { title: t("ISO"), field: "isoCode", width: 70 },
      usdColumn(t("Imports"), "valueUsd"),
      pctColumn(t("Share"), "share"),
      ...(single ? [tonsColumn(t("Tonnes"), "quantityTonnes")] : []),
      ...geoColumns(),
    ],
  });
  suppliers.on("rowClick", (_, row) => profile(row.getData().countryCode));

  const where = root.querySelector("#where");
  loadWorld()
    .then(() => where.isConnected && zoomable(chart(where.querySelector("#map"), {
      tooltip: { formatter: (p) => (p.data?.supplier ? `${esc(p.data.supplier.countryName)}: ${usd(p.data.supplier.valueUsd)} (${pct(p.data.supplier.share)})` : "") },
      visualMap: {
        min: 0,
        max: ranked[0].share,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        itemWidth: 10,
        itemHeight: 120,
        text: [pct(ranked[0].share, 0), pct(0, 0)],
        textStyle: { color: css("--muted") },
        inRange: { color: [css("--supply-soft"), css("--supply")] },
      },
      series: [{
        type: "map",
        map: "world",
        selectedMode: false,
        left: 0,
        right: 0,
        top: 0,
        bottom: 34,
        itemStyle: { areaColor: css("--land"), borderColor: css("--border"), borderWidth: 0.6 },
        emphasis: { label: { show: false }, itemStyle: { areaColor: css("--accent") } },
        data: [
          ...ranked.map((s) => ({ name: shapeId(s.countryCode), value: s.share, supplier: s })),
          { name: shapeId(state.reporter.countryCode), itemStyle: { areaColor: css("--warn") }, emphasis: { disabled: true } },
        ],
      }],
    }), "series").on("click", (p) => profile(p.data?.supplier?.countryCode)))
    .catch(() => where.remove());

  const years = data.years.map((y) => String(y.year));
  chart(root.querySelector("#trend"), {
    grid: { left: 70, right: 60, top: 40, bottom: 30 },
    legend: { textStyle: { color: css("--muted") } },
    tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? t("no recorded flow") : v > 1 ? usd(v) : index(v)) },
    xAxis: { ...axis(), type: "category", data: years },
    yAxis: [
      { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
      { ...axis(), type: "value", min: 0, max: 1, splitLine: { show: false } },
    ],
    series: [
      { name: t("Imports"), type: "bar", data: data.years.map((y) => y.metrics?.totalUsd ?? null), itemStyle: { color: css("--accent-2") } },
      { name: t("Supplier HHI"), type: "line", yAxisIndex: 1, data: data.years.map((y) => y.metrics?.hhi ?? null), itemStyle: { color: css("--warn") } },
      ...(single
        ? [{ name: t("World exporter HHI"), type: "line", yAxisIndex: 1, lineStyle: { type: "dashed" }, data: data.years.map((y) => y.world?.hhi ?? null), itemStyle: { color: css("--accent") } }]
        : []),
    ],
  });

  chart(root.querySelector("#exports"), {
    grid: { left: 70, right: 60, top: 40, bottom: 30 },
    legend: { textStyle: { color: css("--muted") } },
    tooltip: { trigger: "axis" },
    xAxis: { ...axis(), type: "category", data: years },
    yAxis: [
      { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
      { ...axis(), type: "value", min: 0, splitLine: { show: false } },
    ],
    series: [
      { name: t("Exports"), type: "bar", data: data.years.map((y) => y.exports?.totalUsd ?? null), itemStyle: { color: css("--accent") }, tooltip: { valueFormatter: usd } },
      { name: t("RCA"), type: "line", yAxisIndex: 1, data: data.years.map((y) => y.exports?.rca ?? null), itemStyle: { color: css("--warn") }, tooltip: { valueFormatter: index } },
    ],
  });

  const totals = {};
  for (const y of recorded) for (const s of y.suppliers) totals[s.countryCode] = (totals[s.countryCode] ?? 0) + s.valueUsd;
  const tracked = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, TRACKED).map(([c]) => Number(c));
  chart(root.querySelector("#shares"), {
    grid: { left: 60, right: 30, top: 40, bottom: 30 },
    legend: { type: "scroll", textStyle: { color: css("--muted") } },
    tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? t("n/a") : pct(v)) },
    xAxis: { ...axis(), type: "category", data: years },
    yAxis: { ...axis(), type: "value", min: 0, max: 1, axisLabel: { color: css("--muted"), formatter: (v) => pct(v, 0) } },
    color: [css("--warn"), css("--accent"), css("--accent-2"), css("--muted"), "#b48a2c"],
    series: tracked.map((country) => ({
      type: "line",
      name: recorded.flatMap((y) => y.suppliers).find((s) => s.countryCode === country).countryName,
      data: data.years.map((y) => (y.metrics ? y.suppliers.find((s) => s.countryCode === country)?.share ?? 0 : null)),
    })),
  });

  if (current.world) {
    const share = Object.fromEntries(ranked.map((s) => [s.countryCode, s.share]));
    const exporters = table(root.querySelector("#exporters"), {
      data: current.world.topExporters.map((e) => ({ ...e, reporter: share[e.countryCode] ?? 0 })),
      pagination: false,
      rowFormatter: (row) => row.getData().reporter === 0 && row.getElement().classList.add("untapped"),
      columns: [
        { title: t("Country"), field: "countryName", minWidth: 140 },
        pctColumn(t("Share of world exports"), "share"),
        pctColumn(t("Share of imports"), "reporter"),
      ],
    });
    exporters.on("rowClick", (_, row) => profile(row.getData().countryCode));
  }

  if (!single) {
    const members = table(root.querySelector("#members"), {
      data: data.products,
      paginationSize: 10,
      columns: [
        { title: t("Code"), field: "productCode", width: 90 },
        { title: t("Product"), field: "description", tooltip: true },
      ],
    });
    members.on("rowClick", (_, row) => (location.hash = `#/product/${row.getData().productCode}?year=${current.year}`));
  }
}

async function search(root, q) {
  root.append(html(`
    <div class="head">
      <h1>${t("Investigate a product")}</h1>
      <p class="lede">${t("Search by HS code (2, 4 or 6 digits) or by words in the description. A 2 or 4 digit code opens the whole chapter or heading.")}</p>
      <form class="controls"><label>${t("Product")} <input name="q" type="search" value="${esc(q)}" placeholder="1001, wheat, fertilizers" autofocus></label></form>
    </div>
    <div class="panel"><h2>${t("Chapters, headings and products")}</h2>
      <p>${t("The Harmonized System files every good under a six digit code. The first two digits are its chapter, such as 10 for cereals. The first four are its heading, such as 1001 for wheat and meslin. All six are the product, such as 100119 for durum wheat other than seed, the finest level BACI records.")}</p></div>
    <div class="panel"><h2>${t("Case studies")}</h2><p>${CASE_STUDIES.map(([c, label]) => `<a href="#/product/${c}">${esc(t(label))}</a>`).join(" · ")}</p></div>
    <div class="panel"><h2>${t("Matches")}</h2><div id="matches"></div></div>
  `));
  const input = root.querySelector("input[name=q]");
  const matches = table(root.querySelector("#matches"), {
    paginationSize: 15,
    placeholder: t("Type at least two characters"),
    columns: [
      { title: t("Code"), field: "productCode", width: 90 },
      { title: t("Product"), field: "description", tooltip: true },
      { title: t("Heading"), field: "heading", width: 110 },
    ],
  });
  matches.on("rowClick", (_, row) => (location.hash = `#/product/${row.getData().productCode}`));
  let timer;
  const run = async () => {
    const term = input.value.trim();
    matches.setData(term.length >= 2 ? await api(`/products?${query({ snapshot: state.snapshot._id, q: term })}`) : []);
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(run, 200);
  });
  root.querySelector("form").addEventListener("submit", (e) => {
    e.preventDefault();
    const term = input.value.trim();
    if (/^(\d{2}){1,3}$/.test(term)) location.hash = `#/product/${term}`;
  });
  if (q) run();
}
