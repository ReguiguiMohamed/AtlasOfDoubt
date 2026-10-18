import { t } from "../i18n.js";
import { api, axis, centroid, chart, count, css, doubling, esc, geoColumns, gravity, html, index, km, kpi, loadWorld, pct, pctColumn, query, reach, scoped, shapeId, state, storeTag, table, tonsColumn, unavailable, usd, usdColumn, zoomable } from "../lib.js";

const CASE_STUDIES = [
  ["10", "Cereals (chapter 10)"],
  ["1001", "Wheat and meslin"],
  ["31", "Fertilisers (chapter 31)"],
  ["85", "Electrical machinery and equipment (chapter 85)"],
];
const BARS = 15;
const TRACKED = 5;
const FLOWS = 12;
const ROLES = [
  ["{reporter}", "--warn"],
  ["Supplier", "--accent"],
  ["Buys from the same suppliers", "--accent-2"],
  ["Sells elsewhere, not to {reporter}", "--muted"],
  ["Supplies a supplier", "#b48a2c"],
];

// A force layout of the graph's answers. A country keeps its first role, so a supplier that also buys from another supplier stays a supplier.
function network(node, net, reporter, pick) {
  const nodes = new Map();
  const add = (code, role, value, tip) => nodes.has(code) || nodes.set(code, { code, role, value, tip });
  add(net.reporter, 0, 0, reporter);
  for (const s of net.suppliers) add(s.countryCode, 1, s.valueUsd, t("sells {reporter} {value}", { reporter, value: usd(s.valueUsd) }));
  for (const p of net.peers) add(p.countryCode, 2, p.valueUsd, t("buys {value} from {count} of the same suppliers", { value: usd(p.valueUsd), count: p.sharedSuppliers }));
  for (const x of net.alternatives) add(x.countryCode, 3, x.valueUsd, t("sells {value} to {count} markets, none to {reporter}", { reporter, value: usd(x.valueUsd), count: x.markets }));
  const paths = net.paths.filter((p) => nodes.has(p.via));
  for (const p of paths) add(p.origin, 4, p.valueUsd, t("sells {value} to a supplier of {reporter}", { reporter, value: usd(p.valueUsd) }));
  const links = [
    ...net.suppliers.map((s) => [s.countryCode, net.reporter, s.valueUsd]),
    ...net.links.map((l) => [l.from, l.to, l.valueUsd]),
    ...paths.map((p) => [p.origin, p.via, p.valueUsd]),
  ];
  const biggest = Math.max(...[...nodes.values()].map((n) => n.value));
  const widest = Math.max(...links.map(([, , v]) => v));
  const categories = ROLES.map(([name, color]) => ({ name: t(name, { reporter }), itemStyle: { color: color.startsWith("--") ? css(color) : color } }));
  chart(node, {
    legend: { data: categories.map((c) => c.name), textStyle: { color: css("--muted") } },
    tooltip: {
      formatter: (p) => (p.dataType === "edge"
        ? `${esc(net.names[p.data.source])} → ${esc(net.names[p.data.target])}: ${usd(p.data.value)}`
        : `<b>${esc(p.data.name)}</b>${p.data.code === net.reporter ? "" : ` ${esc(p.data.tip)}`}`),
    },
    series: [{
      type: "graph",
      layout: "force",
      top: 40,
      roam: true,
      draggable: true,
      categories,
      force: { repulsion: 260, edgeLength: [50, 170], gravity: 0.08 },
      label: { show: true, position: "right", color: css("--ink"), fontSize: 11 },
      labelLayout: { hideOverlap: true },
      lineStyle: { color: "source", opacity: 0.55, curveness: 0.15 },
      edgeSymbol: ["none", "arrow"],
      edgeSymbolSize: 7,
      emphasis: { focus: "adjacency", lineStyle: { opacity: 0.9 } },
      data: [...nodes.values()].map((n) => ({
        id: String(n.code), code: n.code, name: net.names[n.code], value: n.value, tip: n.tip, category: n.role,
        symbolSize: n.role ? 10 + 34 * Math.sqrt(n.value / biggest) : 46,
      })),
      links: links.map(([from, to, value]) => ({ source: String(from), target: String(to), value, lineStyle: { width: 1 + 6 * Math.sqrt(value / widest) } })),
    }],
  }).on("click", (p) => p.dataType === "node" && p.data.code !== net.reporter && pick(p.data.code));
  return nodes.size;
}

// Bars of markets that also levy per-kilo or per-unit duties, which no percentage can show.
const HATCH = { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 4], rotation: -Math.PI / 4, color: "rgba(255, 255, 255, 0.55)" };

// A market's rate, or the top of its range where several codes met in one HS2012 code.
const charged = (m) => m.rate ?? m.maxRate;
const rateText = (m) => (m.rate != null ? pct(m.rate / 100) : t("{low} to {high}", { low: pct(m.minRate / 100), high: pct(m.maxRate / 100) }));

// Every market's MFN tariff on one product, as a map and as a wall of bars from the highest to duty free.
function tariffWall(panel, data, reporter, profile) {
  const markets = data.markets;
  if (!markets.length) return panel.remove();
  const values = markets.map(charged).sort((a, b) => a - b);
  // One prohibitive rate would wash every other colour out, so the scale stops at the 95th percentile.
  const top = Math.max(values[Math.floor((values.length - 1) * 0.95)], 1);
  const shade = (v) => echarts.color.lerp(Math.min(v / top, 1), [css("--tariff-soft"), css("--tariff")]);
  const own = data.own;
  const highest = markets[0];
  const sold = markets.filter((m) => m.exportsUsd);
  const soldUsd = sold.reduce((sum, m) => sum + m.exportsUsd, 0);
  const freeUsd = sold.filter((m) => charged(m) === 0).reduce((sum, m) => sum + m.exportsUsd, 0);
  const biggest = Math.max(...sold.map((m) => m.exportsUsd));
  panel.querySelector(".kpis").innerHTML = [
    kpi(t("Tariff of {reporter}", { reporter }), own ? rateText(own) : t("n/a"), own ? `${esc(own.schedule)} ${own.year}` : t("no TRAINS schedule")),
    kpi(t("Median market"), pct(values[Math.floor(values.length / 2)] / 100)),
    kpi(t("Duty free"), t("{count} of {total} markets", { count: values.filter((v) => v === 0).length, total: markets.length })),
    kpi(t("Under a preference"), t("{count} of {total} markets", { count: markets.filter((m) => m.preference).length, total: markets.length })),
    kpi(t("Highest"), rateText(highest), esc(highest.countryName)),
    kpi(t("Markets {reporter} sells to", { reporter }), t("{count} of {total} markets", { count: sold.length, total: markets.length }), sold.length ? t("{value} in {year}", { value: usd(soldUsd), year: data.exportYear }) : ""),
    kpi(t("Of its sales, duty free"), sold.length ? pct(freeUsd / soldUsd) : t("n/a")),
  ].join("");
  const tip = (m) => `<b>${esc(m.countryName)}</b>: ${rateText(m)}<br>${esc(m.schedule)} ${m.mfn.year}`
    + (m.preference ? `<br>${t("{agreement}, against {rate} most-favoured-nation", { agreement: esc(t(m.preference.name)), rate: rateText(m.mfn) })}` : "")
    + (m.prefLines ? `<br>${t("The preference covers {count} of {total} national lines", { count: m.prefLines, total: m.nationalLines })}` : "")
    + (m.sourceCodes > 1 ? `, ${t("range over {count} codes", { count: m.sourceCodes })}` : "")
    + (m.naLines ? `<br>${t("{count} of {total} national lines levy a non-ad-valorem duty, left out of the rate", { count: m.naLines, total: m.nationalLines })}` : "")
    + (m.exportsUsd ? `<br>${t("{reporter} sold it {value} in {year}", { reporter, value: usd(m.exportsUsd), year: data.exportYear })}` : "");
  const mine = (m) => ({
    ...(m.preference ? { borderColor: css("--accent"), borderWidth: 1.4, borderType: "dashed" } : {}),
    ...(m.countryCode === data.reporter ? { borderColor: css("--warn"), borderWidth: 2 } : m.exportsUsd ? { borderColor: css("--sold"), borderWidth: 1.6 } : {}),
  });

  loadWorld()
    .then(() => panel.isConnected && zoomable(chart(panel.querySelector("#tariff-map"), {
      tooltip: { formatter: (p) => (p.data?.market ? tip(p.data.market) : "") },
      visualMap: {
        min: 0,
        max: top,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        itemWidth: 10,
        itemHeight: 120,
        text: [`${pct(top / 100, 0)}+`, pct(0, 0)],
        textStyle: { color: css("--muted") },
        inRange: { color: [css("--tariff-soft"), css("--tariff")] },
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
        data: markets.map((m) => ({ name: shapeId(m.countryCode), value: charged(m), market: m, itemStyle: mine(m) })),
      }],
    }), "series").on("click", (p) => profile(p.data?.market?.countryCode)))
    .catch(() => panel.querySelector("#tariff-map").remove());

  // A range floats from its lowest to its highest rate on a transparent base.
  const base = markets.map((m) => (m.rate != null ? 0 : m.minRate));
  chart(panel.querySelector("#tariff-wall"), {
    // ECharts draws a decal only while this is on.
    aria: { enabled: true, decal: { show: true } },
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    tooltip: { formatter: (p) => tip(markets[p.dataIndex]) },
    xAxis: {
      ...axis(),
      type: "category",
      data: markets.map((m) => (m.exportsUsd ? { value: m.isoCode, textStyle: { color: css("--sold"), fontWeight: 600 } } : m.isoCode)),
      axisLabel: { color: css("--muted"), fontSize: 9, interval: "auto" },
    },
    yAxis: { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: (v) => pct(v / 100, 0) } },
    series: [
      { type: "bar", stack: "rate", silent: true, data: base, itemStyle: { color: "transparent", decal: { symbol: "none" } } },
      {
        type: "bar",
        stack: "rate",
        barCategoryGap: "15%",
        data: markets.map((m, i) => ({
          value: charged(m) - base[i],
          itemStyle: {
            ...(m.countryCode === data.reporter ? { color: css("--warn") } : { color: shade(charged(m)), opacity: m.rate != null ? 1 : 0.55 }),
            decal: m.naLines ? HATCH : { symbol: "none" },
          },
        })),
        markLine: {
          silent: true,
          symbol: "none",
          label: { formatter: t("median"), position: "insideEndTop", color: css("--muted") },
          lineStyle: { color: css("--muted"), type: "dashed" },
          data: [{ yAxis: values[Math.floor(values.length / 2)] }],
        },
      },
      {
        type: "scatter",
        data: markets.map((m) => (m.exportsUsd ? charged(m) : "-")),
        symbolSize: (v, p) => 6 + 18 * Math.sqrt(markets[p.dataIndex].exportsUsd / biggest),
        symbolOffset: [0, -8],
        itemStyle: { color: css("--sold"), borderColor: "#fff", borderWidth: 1, decal: { symbol: "none" } },
        z: 3,
      },
      {
        type: "scatter",
        silent: true,
        symbol: "rect",
        symbolSize: [12, 2],
        data: markets.map((m) => (m.preference ? charged(m.mfn) : "-")),
        itemStyle: { color: css("--accent"), decal: { symbol: "none" } },
        z: 4,
      },
    ],
  }).on("click", (p) => profile(markets[p.dataIndex].countryCode));
}

// The suppliers of each recorded year on one map, shaded by share, with a line flowing from the largest to the reporter.
function supplyMap(panel, recorded, current, located, code, own) {
  const reporter = state.reporter;
  const home = centroid(reporter.countryCode);
  const label = panel.querySelector(".timeline strong");
  const slider = panel.querySelector(".timeline input");
  const play = panel.querySelector(".timeline button");
  const detail = panel.querySelector("#supplier-detail");
  const top = Math.max(...recorded.map((y) => y.metrics.topSupplier.share));
  let shown = current;
  const frame = (y) => {
    const rows = located(y);
    const flows = rows.slice(0, FLOWS).map((s) => ({ s, from: centroid(s.countryCode) })).filter((f) => f.from && home);
    const widest = Math.max(...flows.map((f) => f.s.valueUsd), 1);
    return {
      series: [
        {
          data: [
            ...rows.map((s) => ({
              name: shapeId(s.countryCode), value: s.share, supplier: s,
              itemStyle: own.charged[s.countryCode] ? { borderColor: css("--accent"), borderWidth: 1.4, borderType: "dashed" } : undefined,
            })),
            { name: shapeId(reporter.countryCode), itemStyle: { areaColor: css("--warn") }, home: true },
          ],
        },
        {
          data: flows.map((f) => ({ coords: [f.from, home], supplier: f.s, lineStyle: { width: 1 + 5 * Math.sqrt(f.s.valueUsd / widest) } })),
        },
      ],
    };
  };
  const tip = (s) => [
    `<b>${esc(s.countryName)}</b>`,
    t("{value}, {share} of the imports of {reporter} in {year}", { value: usd(s.valueUsd), share: pct(s.share), reporter: esc(reporter.countryName), year: shown.year }),
    s.distanceKm != null ? km(s.distanceKm) + (s.contiguous ? `, ${t("Shares a border")}` : "") : "",
    own.charged[s.countryCode] ? t("Tariff of {reporter} on it: {rate} under {agreement}, against {mfn} most-favoured-nation", { reporter: esc(reporter.countryName), rate: rateText(own.charged[s.countryCode]), agreement: esc(own.charged[s.countryCode].name), mfn: rateText(own.tariff) })
      : own.tariff ? t("Tariff of {reporter} on it: {rate}, most-favoured-nation", { reporter: esc(reporter.countryName), rate: rateText(own.tariff) }) : "",
    `<i>${t("Click for what it sells here")}</i>`,
  ].filter(Boolean).join("<br>");
  const instance = chart(panel.querySelector("#map"), {
    tooltip: { formatter: (p) => (p.data?.supplier ? tip(p.data.supplier) : p.data?.home ? `<b>${esc(reporter.countryName)}</b>` : "") },
    visualMap: {
      seriesIndex: 0,
      min: 0,
      max: top,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 10,
      itemHeight: 120,
      text: [pct(top, 0), pct(0, 0)],
      textStyle: { color: css("--muted") },
      inRange: { color: [css("--supply-soft"), css("--supply")] },
    },
    geo: {
      map: "world",
      left: 0,
      right: 0,
      top: 0,
      bottom: 34,
      selectedMode: false,
      itemStyle: { areaColor: css("--land"), borderColor: css("--border"), borderWidth: 0.6 },
      emphasis: { label: { show: false }, itemStyle: { areaColor: css("--accent") } },
    },
    series: [
      { type: "map", geoIndex: 0 },
      {
        type: "lines",
        coordinateSystem: "geo",
        zlevel: 1,
        effect: { show: true, period: 5, trailLength: 0.35, symbol: "arrow", symbolSize: 5, color: css("--warn") },
        lineStyle: { color: css("--supply"), opacity: 0.5, curveness: 0.25 },
      },
    ],
  });
  zoomable(instance, "geo");
  const show = (i) => {
    shown = recorded[i];
    slider.value = i;
    label.textContent = shown.year;
    instance.setOption(frame(shown));
  };
  show(recorded.indexOf(current));
  slider.addEventListener("input", () => show(Number(slider.value)));
  let timer;
  const stop = () => {
    clearInterval(timer);
    timer = null;
    play.textContent = "▶";
  };
  play.addEventListener("click", () => {
    if (timer) return stop();
    play.textContent = "❚❚";
    if (Number(slider.value) === recorded.length - 1) show(0);
    timer = setInterval(() => {
      if (!panel.isConnected) return stop();
      const next = Number(slider.value) + 1;
      if (next >= recorded.length) return stop();
      show(next);
    }, 900);
  });

  instance.on("click", async (p) => {
    const s = p.data?.supplier;
    if (!s) return;
    const year = shown.year;
    detail.textContent = "";
    const profile = await api(`/countries/${s.countryCode}?${scoped({ year })}`);
    const rows = profile.products.filter((r) => r.productCode.startsWith(code));
    detail.innerHTML = `<h3>${t("What {country} sold {reporter} under {code}, {year}", { country: esc(s.countryName), reporter: esc(reporter.countryName), code, year })}</h3>
      <div></div><p><a href="#/country/${s.countryCode}?year=${year}">${t("Open the profile of {country}", { country: esc(s.countryName) })}</a></p>`;
    table(detail.querySelector("div"), {
      data: rows,
      paginationSize: 8,
      columns: [
        { title: t("Code"), field: "productCode", width: 90 },
        { title: t("Product"), field: "description", tooltip: true },
        usdColumn(t("Imports"), "valueUsd"),
        pctColumn(t("Share"), "share"),
        { title: t("Rank"), field: "rank", hozAlign: "right", sorter: "number", width: 100, formatter: (c) => t("{count} of {total}", { count: c.getValue(), total: c.getData().supplierCount }) },
      ],
    }).on("rowClick", (_, row) => (location.hash = `#/product/${row.getData().productCode}?year=${year}`));
  });
}

export default async function product(root, [code], params) {
  if (!code) return search(root, params.get("q") ?? "");
  const data = await api(`/products/${code}/history?${scoped()}`);
  const reporter = esc(state.reporter.countryName);
  const single = code.length === 6;
  const members = data.products.length;
  const first = data.products[0];
  const size = `${t(code.length === 2 ? "Chapter" : "Heading")}, ${members === 1 ? t("1 product") : t("{count} products", { count: count(members) })}`;
  // Snapshots prepared before HS names joined carry none, so a group falls back to its size.
  const named = code.length === 2 ? first.chapterName : first.headingName;
  const title = single ? first.description : named ?? size;
  const crumbs = first.sectionName ? `<nav class="crumbs">${[
    `${t("Section {section}", { section: esc(first.section) })} ${esc(first.sectionName)}`,
    ...(code.length > 2 ? [`<a href="#/product/${first.chapter}">${first.chapter} ${esc(first.chapterName)}</a>`] : []),
    ...(single ? [`<a href="#/product/${first.heading}">${first.heading} ${esc(first.headingName)}</a>`] : []),
  ].join(" › ")}</nav>` : "";
  const recorded = data.years.filter((y) => y.metrics);
  if (!recorded.length) {
    root.append(html(`<div class="head"><h1><span class="code">${esc(code)}</span> ${esc(title)}</h1>
      <p class="notice">${t("BACI records no imports of this code into {reporter} between {from} and {to}.", { reporter, from: state.snapshot.years[0], to: state.snapshot.years.at(-1) })}</p></div>`));
    return;
  }
  const wanted = Number(params.get("year"));
  const current = recorded.find((y) => y.year === wanted) ?? recorded.at(-1);
  const m = current.metrics;
  const located = (y) => y.suppliers.map((s) => ({ ...s, ...data.geography[s.countryCode] }));
  const far = state.snapshot.geography && reach(located(current));

  root.append(html(`
    <div class="head">
      ${crumbs}
      <a class="back-link" href="#/product">← ${t("Find another product")}</a>
      <h1><span class="code">${esc(code)}</span> ${esc(title)}</h1>
      <p class="lede">${single || !named ? "" : `${esc(size)}. `}${t(single ? "HS6 product {code}, in heading {heading} of chapter {chapter}." : "Every HS6 product whose code starts with {code}. Supplier values are summed across the group before shares and the HHI are computed.", { code, heading: code.slice(0, 4), chapter: code.slice(0, 2) })}
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
      ${far ? kpi(t("Average distance"), km(far.km), t("{share} from neighbours", { share: pct(far.neighbours) })) : ""}
    </div>
    <div class="panel" id="where"><h2>${t("Where the supply comes from")} ${storeTag("MongoDB documents")}</h2>
      <p>${t("Shaded by share of the imports of {reporter}, with {reporter} in red, and a line flows to it from each of the {count} largest suppliers. Play the years or drag the slider, hover a country for its figures and click one for what it sells {reporter} here. Very small countries do not show at this scale and are listed in the table.", { reporter, count: FLOWS })}</p>
      <div class="controls timeline"><button type="button" aria-label="${t("Play the years")}">▶</button>
        <input type="range" min="0" max="${recorded.length - 1}" value="${recorded.indexOf(current)}" aria-label="${t("Year")}"><strong></strong></div>
      <div class="chart map" id="map"></div>
      <div id="supplier-detail"></div></div>
    ${single && state.snapshot.tariffs ? `<div class="panel" id="tariff-panel"><h2>${t("The tariff wall: what each market charges on it")} ${storeTag("MongoDB documents")}</h2>
      <p>${t("The tariff each market charges {reporter}, from its latest TRAINS schedule: the lower of its most-favoured-nation rate and the best preference covering {reporter}. A dashed blue outline marks a preference, and a blue tick on its bar the most-favoured-nation rate it replaces. Members of one customs union, like the EU, charge each other nothing. A rate is the simple average of the national lines under this code, so a market can charge more or less on one variety. Where several codes of a newer HS edition meet in this one, the bar floats over their range and no average is made. {reporter} is outlined in red. Click a country for its profile.", { reporter })}
      ${t("A hatched bar marks a market that also levies duties per kilo or per unit, which the rate leaves out.")}
      ${t("A green dot, sized by value, marks each market {reporter} sold it to in {year}, and the map outlines them in green.", { reporter, year: state.snapshot.years.at(-1) })}</p>
      <div class="kpis"></div>
      <div class="chart map" id="tariff-map"></div>
      <div class="chart" id="tariff-wall"></div></div>` : ""}
    <div class="grid">
      <div class="panel"><h2>${t("Suppliers in {year}", { year: current.year })}</h2><div class="chart tall" id="bars"></div></div>
      <div class="panel"><h2>${t("Supplier table")}</h2><div id="suppliers"></div></div>
    </div>
    ${far ? `<div class="grid" style="margin-top:1.25rem">
      <div class="panel"><h2>${t("Distance and value, {year}", { year: current.year })}</h2>
        <p>${t("Each bubble is a supplier, sized by its share, on log scales. Neighbours and partners sharing an official language stand out.")} <span id="doubling"></span></p>
        <div class="chart tall" id="gravity"></div></div>
      <div class="panel"><h2>${t("How far the supply travels, {from} to {to}", { from: data.years[0].year, to: data.years.at(-1).year })}</h2>
        <p>${t("The import-weighted distance between the most populated cities, and the share bought from countries across a land border.")}</p>
        <div class="chart tall" id="travel"></div></div>
    </div>` : ""}
    ${state.snapshot.graph && code.length >= 4 ? `<div class="panel" id="network-panel" style="margin-top:1.25rem">
      <h2>${t("Supplier network of heading {heading}, {year}", { heading: code.slice(0, 4), year: state.snapshot.graph.year })} ${storeTag("Ladybug graph")}</h2>
      <p>${t("From the Ladybug trade graph: {reporter} in red, its largest suppliers, the markets buying from the same suppliers, exporters that sell this heading elsewhere but not to {reporter}, and the countries supplying its suppliers. Arrows follow the goods. A two-step link is trade between partners, not a proven supply chain. Drag, zoom and click a country.", { reporter })}</p>
      <div class="chart tall" id="network"></div></div>` : ""}
    <div class="panel" style="margin-top:1.25rem"><h2>${t("Imports and concentration, {from} to {to}", { from: data.years[0].year, to: data.years.at(-1).year })}</h2>
      <div class="chart" id="trend"></div></div>
    <div class="panel"><h2>${t("Shares of the five largest suppliers over time")}</h2><div class="chart" id="shares"></div></div>
    <div class="panel"><h2>${t("Exports of {reporter}, {from} to {to}", { reporter, from: data.years[0].year, to: data.years.at(-1).year })}</h2>
      <p>${t("Revealed comparative advantage compares the share of this code in the exports of {reporter} with its share in world exports. Above 1, {reporter} exports relatively more of it than the world does.", { reporter })}</p>
      <div class="chart" id="exports"></div></div>
    ${single && current.exporters.length ? `<div class="panel" id="alternatives"><h2>${t("Who else sells it, {year}", { year: current.year })}</h2>
      <p>${t("The {count} largest exporters of this product worldwide, against what each sent {reporter}. A large exporter that sends nothing yet, shown in red, is a supplier {reporter} could turn to. The map above outlines in dashed blue the suppliers {reporter} gives a preference, and the others pay its most-favoured-nation tariff.", { reporter, count: current.exporters.length })}</p>
      <form class="controls">
        ${state.snapshot.geography ? `<label>${t("Distance")} <select name="km"><option value="">${t("any")}</option>${[1000, 3000, 6000, 10000].map((k) => `<option value="${k}">${t("under {km}", { km: km(k) })}</option>`).join("")}</select></label>
        <label><input type="checkbox" name="contiguous"> ${t("Shares a border")}</label>
        <label><input type="checkbox" name="commonLanguage"> ${t("Shares an official language")}</label>` : ""}
        <label><input type="checkbox" name="untapped"> ${t("Not yet a supplier")}</label>
        <span class="count" id="alternatives-count"></span>
      </form>
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

  if (far) {
    root.querySelector("#doubling").textContent = doubling(gravity(root.querySelector("#gravity"), located(current), profile));
    const reached = data.years.map((y) => (y.metrics ? reach(located(y)) : null));
    chart(root.querySelector("#travel"), {
      grid: { left: 70, right: 60, top: 40, bottom: 30 },
      legend: { textStyle: { color: css("--muted") } },
      tooltip: { trigger: "axis" },
      xAxis: { ...axis(), type: "category", data: data.years.map((y) => String(y.year)) },
      yAxis: [
        { ...axis(), type: "value", scale: true, axisLabel: { color: css("--muted"), formatter: km } },
        { ...axis(), type: "value", min: 0, max: 1, splitLine: { show: false }, axisLabel: { color: css("--muted"), formatter: (v) => pct(v, 0) } },
      ],
      series: [
        { name: t("Average distance"), type: "line", smooth: true, areaStyle: { opacity: 0.12 }, data: reached.map((r) => r?.km ?? null), itemStyle: { color: css("--accent") }, tooltip: { valueFormatter: km } },
        { name: t("Share from neighbours"), type: "bar", yAxisIndex: 1, barMaxWidth: 18, data: reached.map((r) => r?.neighbours ?? null), itemStyle: { color: css("--warn"), opacity: 0.6 }, tooltip: { valueFormatter: pct } },
      ],
    });
  }

  const suppliers = table(root.querySelector("#suppliers"), {
    data: located(current),
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

  // The tariff fetch fills this in, and the map's tooltip reads it once it is there.
  const own = { tariff: null, charged: {} };
  const where = root.querySelector("#where");
  loadWorld()
    .then(() => where.isConnected && supplyMap(where, recorded, current, located, code, own))
    .catch(() => where.remove());

  const walled = root.querySelector("#tariff-panel");
  if (walled) {
    api(`/products/${code}/tariffs?${scoped()}`)
      .then((rates) => {
        own.tariff = rates.own?.mfn ?? null;
        own.charged = rates.charged;
        return walled.isConnected && tariffWall(walled, rates, reporter, profile);
      })
      .catch(() => walled.remove());
  }

  const graphed = root.querySelector("#network-panel");
  if (graphed) {
    api(`/products/${code}/network?${scoped()}`)
      .then((net) => graphed.isConnected && network(graphed.querySelector("#network"), net, state.reporter.countryName, profile) < 2 && graphed.remove())
      .catch((e) => (e.status === 503 ? graphed.querySelector("#network").replaceWith(html(unavailable("Ladybug graph")).firstElementChild) : graphed.remove()));
  }

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

  const alternatives = root.querySelector("#alternatives");
  if (alternatives) {
    const share = Object.fromEntries(ranked.map((s) => [s.countryCode, s.share]));
    const rows = current.exporters.map((e) => ({ ...e, ...data.geography[e.countryCode], reporter: share[e.countryCode] ?? 0 }));
    const exporters = table(alternatives.querySelector("#exporters"), {
      data: rows,
      pagination: false,
      rowFormatter: (row) => row.getData().reporter === 0 && row.getElement().classList.add("untapped"),
      columns: [
        { title: t("Country"), field: "countryName", minWidth: 140 },
        usdColumn(t("World exports"), "valueUsd"),
        pctColumn(t("Share of world exports"), "share"),
        pctColumn(t("Share of imports"), "reporter"),
        ...geoColumns(),
      ],
    });
    exporters.on("rowClick", (_, row) => profile(row.getData().countryCode));
    const form = alternatives.querySelector("form");
    const narrow = () => {
      const f = Object.fromEntries(new FormData(form));
      const keep = (r) => (!f.km || (r.distanceKm != null && r.distanceKm < Number(f.km)))
        && (!f.contiguous || r.contiguous) && (!f.commonLanguage || r.commonLanguage) && (!f.untapped || r.reporter === 0);
      exporters.setFilter(keep);
      const shown = rows.filter(keep);
      alternatives.querySelector("#alternatives-count").textContent = t("{shown} of {total} exporters, {untapped} not yet supplying {reporter}", {
        shown: shown.length, total: rows.length, untapped: shown.filter((r) => r.reporter === 0).length, reporter: state.reporter.countryName,
      });
    };
    form.addEventListener("change", narrow);
    form.addEventListener("submit", (e) => e.preventDefault());
    exporters.on("tableBuilt", narrow);
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
      // A chapter or heading whose HS name matched comes first.
      { title: t("Product"), field: "description", tooltip: true, formatter: (c) => {
        const r = c.getData();
        return r.level ? `<strong>${esc(r.description)}</strong> <span class="muted">${t(r.level === "chapter" ? "Chapter" : "Heading")}</span>` : esc(r.description);
      } },
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
