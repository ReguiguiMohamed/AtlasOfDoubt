import { t } from "../i18n.js";
import { TUNISIA, api, axis, chart, count, css, esc, html, kpi, loadWorld, pct, pctColumn, query, shapeId, state, table, usd, usdColumn, zoomable } from "../lib.js";

const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;

export default async function seaRoutes(root, _, params) {
  const code = params.get("code") ?? "";
  const data = await api(`/routes?${query({ snapshot: state.snapshot._id, year: params.get("year"), code })}`);
  const strait = Object.fromEntries(data.chokepoints.map((c) => [c.id, c]));
  const items = [...data.chokepoints, ...data.routes];
  const via = (r) => (r.via?.length ? r.via.map((id) => t(strait[id].name)).join(" → ") : t("no chokepoint"));
  const link = (extra) => `#/routes?${query({ year: data.year, code, ...extra })}`;
  const ranked = [...data.chokepoints].sort((a, b) => b.valueUsd - a.valueUsd);
  let selected = items.find((i) => i.id === params.get("select")) ?? ranked[0];

  root.append(html(`
    <div class="head">
      <h1>${t("Sea routes and chokepoints")}</h1>
      <p class="lede">${t("Each supplier country is given the usual sea lane to Tunis and the straits on it, so the value behind a strait is what a closure would put at risk. BACI does not record transport, so the routes are a model, not shipping data.")}</p>
      <form class="controls">
        <label>${t("Year")} <select name="year">${state.snapshot.years
          .map((y) => `<option ${y === data.year ? "selected" : ""}>${y}</option>`).reverse().join("")}</select></label>
        <label>${t("HS code, optional")} <input name="code" value="${esc(code)}" placeholder="10, 1001, 100199" pattern="\\d{2}(\\d{2}){0,2}" size="12"></label>
        <button class="primary">${t("Show")}</button>
        ${code ? `<a href="#/product/${esc(code)}?year=${data.year}">${t("Product {code}", { code: esc(code) })}</a>` : ""}
      </form>
    </div>
    <div class="kpis">
      ${kpi(t("Imports"), usd(data.totalUsd), code ? t("HS {code}, {year}", { code, year: data.year }) : String(data.year))}
      ${ranked.slice(0, 4).map((c) => kpi(t(c.name), pct(c.share), usd(c.valueUsd))).join("")}
    </div>
    <div class="panel" id="where"><h2>${t("Routes to Tunisia, {year}", { year: data.year })}</h2>
      <p>${t("Line width follows the value carried and circles mark the straits. Hover for a summary, click for the detail below.")}</p>
      <div class="chart map" id="map"></div></div>
    <div class="panel" id="detail"></div>
    <div class="grid">
      <div class="panel"><h2>${t("Chokepoints compared, {year}", { year: data.year })}</h2><div class="chart" id="bars"></div></div>
      <div class="panel"><h2>${t("Share of imports through each chokepoint")}</h2><div class="chart" id="shares"></div></div>
    </div>
    <div class="panel" style="margin-top:1.25rem"><h2>${t("Routes compared, {year}", { year: data.year })}</h2><div id="routes"></div>
      ${data.unrouted.valueUsd > 0 ? `<p>${t("{value} came from entries with no modelled route: {names}.", {
        value: usd(data.unrouted.valueUsd), names: esc(data.unrouted.countries.map((c) => c.countryName).join(", ")),
      })}</p>` : ""}</div>`));

  root.querySelector("form").addEventListener("submit", (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    location.hash = link({ year: form.get("year"), code: form.get("code").trim(), select: selected.id });
  });

  const tip = (i) => [
    `<strong>${esc(t(i.name))}</strong>`,
    i.path !== undefined ? esc(via(i)) : esc(t("Routes through it: {routes}", { routes: i.routes.map((id) => t(data.routes.find((r) => r.id === id).name)).join(", ") })),
    t("{value}, {share} of imports", { value: usd(i.valueUsd), share: pct(i.share) }),
    ...i.countries.slice(0, 4).map((c) => `${esc(c.countryName)}: ${usd(c.valueUsd)}`),
  ].join("<br>");

  const widest = Math.max(...data.routes.map((r) => r.valueUsd)) || 1;
  const largest = ranked[0].valueUsd || 1;
  const mapOption = () => ({
    geo: {
      map: "world",
      silent: true,
      left: 0, right: 0, top: 0, bottom: 0,
      itemStyle: { areaColor: css("--tint"), borderColor: css("--line") },
      regions: [
        ...selected.countries.map((c) => ({ name: shapeId(c.countryCode), itemStyle: { areaColor: css("--accent-2") } })),
        { name: TUNISIA, itemStyle: { areaColor: css("--warn") } },
      ],
    },
    series: [
      {
        id: "lines",
        type: "lines",
        coordinateSystem: "geo",
        polyline: true,
        effect: { show: !calm, constantSpeed: 30, symbol: "circle", symbolSize: 3, trailLength: 0, color: css("--accent") },
        emphasis: { focus: "self", lineStyle: { color: css("--warn"), opacity: 1 } },
        data: data.routes.filter((r) => r.path && r.valueUsd > 0).map((r) => ({
          name: r.name,
          coords: r.path,
          item: r,
          lineStyle: {
            width: 1.5 + 9 * (r.valueUsd / widest),
            color: selected.id === r.id || selected.routes?.includes(r.id) ? css("--warn") : css("--accent"),
            opacity: 0.55,
          },
        })),
      },
      {
        id: "points",
        type: "scatter",
        coordinateSystem: "geo",
        z: 3,
        symbolSize: (v) => 8 + 22 * Math.sqrt(v[2] / largest),
        label: { show: true, position: "right", color: css("--ink"), fontSize: 11, formatter: (p) => t(p.data.item.name) },
        data: data.chokepoints.map((c) => ({
          name: c.name,
          value: [...c.at, c.valueUsd],
          item: c,
          itemStyle: { color: selected.id === c.id ? css("--warn") : css("--ink"), borderColor: "#fff", borderWidth: 1 },
        })),
      },
    ],
  });

  let map;
  const where = root.querySelector("#where");
  loadWorld()
    .then(() => {
      if (!where.isConnected) return;
      map = zoomable(chart(where.querySelector("#map"), { tooltip: { formatter: (p) => (p.data?.item ? tip(p.data.item) : "") }, ...mapOption() }), "geo");
      map.on("click", (p) => p.data?.item && select(p.data.item));
    })
    .catch(() => where.remove());

  const bars = chart(root.querySelector("#bars"), {
    grid: { left: 150, right: 70, top: 10, bottom: 30 },
    tooltip: { formatter: (p) => tip(ranked[p.dataIndex]) },
    xAxis: { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
    yAxis: { type: "category", inverse: true, data: ranked.map((c) => t(c.name)), axisLabel: { color: css("--ink") } },
    series: [{
      type: "bar",
      barMaxWidth: 24,
      data: ranked.map((c) => c.valueUsd),
      label: { show: true, position: "right", color: css("--muted"), formatter: (p) => pct(ranked[p.dataIndex].share) },
    }],
  });
  bars.on("click", (p) => select(ranked[p.dataIndex]));

  chart(root.querySelector("#shares"), {
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    legend: { top: 0, type: "scroll", textStyle: { color: css("--muted") } },
    tooltip: { trigger: "axis", valueFormatter: (v) => pct(v) },
    xAxis: { ...axis(), type: "category", data: state.snapshot.years.map(String) },
    yAxis: { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: (v) => pct(v, 0) } },
    series: ranked.map((c) => ({ name: t(c.name), type: "line", showSymbol: false, data: c.years.map((y) => y.share) })),
  });

  const routeTable = table(root.querySelector("#routes"), {
    data: [...data.routes].sort((a, b) => b.valueUsd - a.valueUsd),
    columns: [
      { title: t("Route"), field: "name", formatter: (c) => esc(t(c.getValue())), minWidth: 200 },
      { title: t("Chokepoints"), field: "via", formatter: (c) => esc(via(c.getRow().getData())), minWidth: 220, headerSort: false },
      usdColumn(t("Imports"), "valueUsd"),
      pctColumn(t("Share of imports"), "share"),
      { title: t("Countries"), field: "countries", hozAlign: "right", sorter: (a, b) => a.length - b.length, formatter: (c) => c.getValue().length, width: 110 },
    ],
  });
  routeTable.on("rowClick", (_, row) => select(row.getData()));

  const detail = root.querySelector("#detail");
  detail.append(html(`
    <h2 id="title"></h2><p id="lane"></p>
    <div class="kpis" id="figures"></div>
    <p id="simulate"></p>
    <div class="grid">
      <div><h2>${t("Value and share, {from} to {to}", { from: state.snapshot.years[0], to: state.snapshot.years.at(-1) })}</h2><div class="chart" id="trend"></div></div>
      <div><h2>${t("Countries")}</h2><div id="countries"></div></div>
    </div>
    <h2 style="margin-top:1.25rem">${t("Products most exposed, {year}", { year: data.year })}</h2>
    <p>${t("Import value that would stop if every listed country lost this route, with no rerouting.")}</p>
    <div id="products"></div>`));
  const trend = chart(detail.querySelector("#trend"), {
    grid: { left: 70, right: 50, top: 30, bottom: 30 },
    legend: { top: 0, textStyle: { color: css("--muted") } },
    tooltip: { trigger: "axis" },
    xAxis: { ...axis(), type: "category", data: state.snapshot.years.map(String) },
    yAxis: [
      { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
      { type: "value", splitLine: { show: false }, axisLabel: { color: css("--muted"), formatter: (v) => pct(v, 0) } },
    ],
  });
  const countries = table(detail.querySelector("#countries"), {
    paginationSize: 8,
    columns: [
      { title: t("Country"), field: "countryName", minWidth: 140 },
      usdColumn(t("Imports"), "valueUsd"),
      pctColumn(t("Share"), "share"),
    ],
  });
  countries.on("rowClick", (_, row) => row.getData().isoCode && (location.hash = `#/country/${row.getData().countryCode}?year=${data.year}`));
  const exposed = table(detail.querySelector("#products"), {
    paginationSize: 10,
    placeholder: "…",
    columns: [
      { title: t("Code"), field: "productCode", width: 90 },
      { title: t("Description"), field: "description", minWidth: 260 },
      usdColumn(t("Imports"), "totalUsd"),
      usdColumn(t("Through this route"), "affectedUsd"),
      pctColumn(t("Exposed"), "exposureShare"),
    ],
  });
  exposed.on("rowClick", (_, row) => (location.hash = `#/product/${row.getData().productCode}?year=${data.year}`));
  const built = Promise.all([countries, exposed].map((grid) => new Promise((done) => grid.on("tableBuilt", done))));

  let asked = 0;
  async function select(item) {
    selected = item;
    history.replaceState(null, "", link({ select: item.id }));
    map?.setOption(mapOption());
    const suppliers = item.countries.filter((c) => c.isoCode).map((c) => c.countryCode);
    const scenario = `#/scenario?${query({
      mode: code ? "product" : "country", code, year: data.year, reduction: 100, suppliers: suppliers.join(","),
    })}`;
    detail.querySelector("#title").textContent = t(item.name);
    detail.querySelector("#lane").textContent = item.path !== undefined
      ? t("Modelled lane: {via}.", { via: via(item) })
      : t("Routes through it: {routes}.", { routes: item.routes.map((id) => t(data.routes.find((r) => r.id === id).name)).join(", ") });
    detail.querySelector("#figures").innerHTML = `
      ${kpi(t("Imports through it"), usd(item.valueUsd), String(data.year))}
      ${kpi(t("Share of imports"), pct(item.share))}
      ${kpi(t("Countries"), count(item.countries.length))}
      <div class="kpi"><span class="label">${t("Products")}</span><strong id="touched">…</strong></div>`;
    detail.querySelector("#simulate").innerHTML = suppliers.length
      ? `<a href="${scenario}"><button type="button" class="primary">${t("Simulate a closure")}</button></a>` : "";
    trend.setOption({
      series: [
        { name: t("Imports"), type: "bar", data: item.years.map((y) => y.valueUsd), itemStyle: { color: css("--accent-2") }, tooltip: { valueFormatter: usd } },
        { name: t("Share of imports"), type: "line", yAxisIndex: 1, data: item.years.map((y) => y.share), itemStyle: { color: css("--warn") }, tooltip: { valueFormatter: (v) => pct(v) } },
      ],
    });
    await built;
    countries.setData(item.countries);
    exposed.setData([]);

    const touched = detail.querySelector("#touched");
    if (!suppliers.length) {
      touched.textContent = "0";
      return;
    }
    const ticket = ++asked;
    const preview = await api("/scenarios/preview", {
      method: "POST",
      body: JSON.stringify({ snapshot: state.snapshot._id, year: data.year, mode: "country", suppliers, reduction: 1 }),
    });
    if (ticket !== asked || !detail.isConnected) return;
    const products = preview.result.products.filter((p) => p.productCode.startsWith(code));
    touched.textContent = count(products.length);
    exposed.setData(products);
  }
  select(selected);
}
