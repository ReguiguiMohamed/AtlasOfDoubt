import { api, axis, chart, css, esc, html, index, kpi, pct, pctColumn, query, state, table, tonsColumn, usd, usdColumn } from "../lib.js";

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
  const data = await api(`/products/${code}/history?${query({ snapshot: state.snapshot._id })}`);
  const single = code.length === 6;
  const count = data.products.length;
  const title = single ? data.products[0].description : `${code.length === 2 ? "Chapter" : "Heading"}, ${count} product${count === 1 ? "" : "s"}`;
  const recorded = data.years.filter((y) => y.metrics);
  if (!recorded.length) {
    root.append(html(`<div class="head"><h1><span class="code">${esc(code)}</span> ${esc(title)}</h1>
      <p class="notice">BACI records no imports of this code into Tunisia between ${state.snapshot.years[0]} and
      ${state.snapshot.years.at(-1)}.</p></div>`));
    return;
  }
  const wanted = Number(params.get("year"));
  const current = recorded.find((y) => y.year === wanted) ?? recorded.at(-1);
  const m = current.metrics;

  root.append(html(`
    <div class="head">
      <h1><span class="code">${esc(code)}</span> ${esc(title)}</h1>
      <p class="lede">${single ? "" : "Supplier values are summed across the group before shares and the HHI are computed. "}
        Gaps in the trend are years with no recorded flow into Tunisia.</p>
      <form class="controls">
        <label>Year <select name="year">${recorded
          .map((y) => `<option ${y.year === current.year ? "selected" : ""}>${y.year}</option>`).reverse().join("")}</select></label>
        <a href="#/scenario?${query({ mode: "product", code, year: current.year })}"><button type="button" class="primary">Run a disruption scenario</button></a>
      </form>
    </div>
    <div class="kpis">
      ${kpi("Imports", usd(m.totalUsd), String(current.year))}
      ${kpi("Suppliers", m.supplierCount)}
      ${kpi("Largest supplier", pct(m.topSupplier.share), m.topSupplier.countryName)}
      ${kpi("Top 3 share", pct(m.top3Share))}
      ${kpi("HHI", index(m.hhi), m.hhi >= 0.25 ? "highly concentrated" : "")}
      ${current.world ? kpi("World exporter HHI", index(current.world.hhi), `${current.world.topSupplier?.countryName} leads world exports`) : ""}
    </div>
    <div class="grid">
      <div class="panel"><h2>Suppliers in ${current.year}</h2><div class="chart tall" id="bars"></div></div>
      <div class="panel"><h2>Supplier table</h2><div id="suppliers"></div></div>
    </div>
    <div class="panel" style="margin-top:1.25rem"><h2>Imports and concentration, ${data.years[0].year} to ${data.years.at(-1).year}</h2>
      <div class="chart" id="trend"></div></div>
    <div class="panel"><h2>Shares of the five largest suppliers over time</h2><div class="chart" id="shares"></div></div>
    ${single ? "" : `<div class="panel"><h2>Products in this group</h2><div id="members"></div></div>`}
  `));
  if (m.hhi >= 0.25) root.querySelector(".kpis .kpi:nth-child(5)").classList.add("alert");

  root.querySelector("select[name=year]").addEventListener("change", (e) => {
    location.hash = `#/product/${code}?year=${e.target.value}`;
  });

  const ranked = current.suppliers;
  const shown = ranked.slice(0, BARS);
  const rest = ranked.slice(BARS);
  if (rest.length) {
    shown.push({ countryName: `${rest.length} others`, valueUsd: rest.reduce((a, s) => a + s.valueUsd, 0), share: rest.reduce((a, s) => a + s.share, 0) });
  }
  chart(root.querySelector("#bars"), {
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

  table(root.querySelector("#suppliers"), {
    data: ranked,
    paginationSize: 12,
    columns: [
      { title: "Country", field: "countryName", minWidth: 140 },
      { title: "ISO", field: "isoCode", width: 70 },
      usdColumn("Imports", "valueUsd"),
      pctColumn("Share", "share"),
      ...(single ? [tonsColumn("Tonnes", "quantityTonnes")] : []),
    ],
  });

  const years = data.years.map((y) => String(y.year));
  chart(root.querySelector("#trend"), {
    grid: { left: 70, right: 60, top: 40, bottom: 30 },
    legend: { textStyle: { color: css("--muted") } },
    tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "no recorded flow" : v > 1 ? usd(v) : index(v)) },
    xAxis: { ...axis(), type: "category", data: years },
    yAxis: [
      { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
      { ...axis(), type: "value", min: 0, max: 1, splitLine: { show: false } },
    ],
    series: [
      { name: "Imports", type: "bar", data: data.years.map((y) => y.metrics?.totalUsd ?? null), itemStyle: { color: css("--accent-2") } },
      { name: "Tunisia HHI", type: "line", yAxisIndex: 1, data: data.years.map((y) => y.metrics?.hhi ?? null), itemStyle: { color: css("--warn") } },
      ...(single
        ? [{ name: "World exporter HHI", type: "line", yAxisIndex: 1, lineStyle: { type: "dashed" }, data: data.years.map((y) => y.world?.hhi ?? null), itemStyle: { color: css("--accent") } }]
        : []),
    ],
  });

  const totals = {};
  for (const y of recorded) for (const s of y.suppliers) totals[s.countryCode] = (totals[s.countryCode] ?? 0) + s.valueUsd;
  const tracked = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, TRACKED).map(([c]) => Number(c));
  chart(root.querySelector("#shares"), {
    grid: { left: 60, right: 30, top: 40, bottom: 30 },
    legend: { type: "scroll", textStyle: { color: css("--muted") } },
    tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "n/a" : pct(v)) },
    xAxis: { ...axis(), type: "category", data: years },
    yAxis: { ...axis(), type: "value", min: 0, max: 1, axisLabel: { color: css("--muted"), formatter: (v) => pct(v, 0) } },
    color: [css("--warn"), css("--accent"), css("--accent-2"), css("--muted"), "#b48a2c"],
    series: tracked.map((country) => ({
      type: "line",
      name: recorded.flatMap((y) => y.suppliers).find((s) => s.countryCode === country).countryName,
      data: data.years.map((y) => (y.metrics ? y.suppliers.find((s) => s.countryCode === country)?.share ?? 0 : null)),
    })),
  });

  if (!single) {
    const members = table(root.querySelector("#members"), {
      data: data.products,
      paginationSize: 10,
      columns: [
        { title: "Code", field: "productCode", width: 90 },
        { title: "Product", field: "description", tooltip: true },
        { title: "Years imported", field: "importYears", formatter: (c) => `${c.getValue().length} of ${data.years.length}`, width: 140 },
      ],
    });
    members.on("rowClick", (_, row) => (location.hash = `#/product/${row.getData().productCode}?year=${current.year}`));
  }
}

async function search(root, q) {
  root.append(html(`
    <div class="head">
      <h1>Investigate a product</h1>
      <p class="lede">Search by HS code (2, 4 or 6 digits) or by words in the description. A 2 or 4 digit code
        opens the whole chapter or heading.</p>
      <form class="controls"><label>Product <input name="q" type="search" value="${esc(q)}" placeholder="1001, wheat, fertilizers" autofocus></label></form>
    </div>
    <div class="panel"><h2>Case studies</h2><p>${CASE_STUDIES.map(([c, label]) => `<a href="#/product/${c}">${esc(label)}</a>`).join(" · ")}</p></div>
    <div class="panel"><h2>Matches</h2><div id="matches"></div></div>
  `));
  const input = root.querySelector("input[name=q]");
  const matches = table(root.querySelector("#matches"), {
    paginationSize: 15,
    placeholder: "Type at least two characters",
    columns: [
      { title: "Code", field: "productCode", width: 90 },
      { title: "Product", field: "description", tooltip: true },
      { title: "Years imported", field: "importYears", formatter: (c) => String(c.getValue().length), width: 140 },
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
