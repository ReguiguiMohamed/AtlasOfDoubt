import { t } from "../i18n.js";
import { api, axis, chart, count, css, esc, html, index, indexColumn, pct, pctColumn, query, scoped, state, storeTag, table, twins, usd, usdColumn } from "../lib.js";

// 0.25 is where the 2010 US Horizontal Merger Guidelines start calling a market highly concentrated (HHI 2500 of 10000).
const HIGH = 0.25;
const THRESHOLDS = [0, 100_000, 1_000_000, 10_000_000, 100_000_000];

async function categories(panel, year) {
  const tree = await api(`/categories?${scoped({ year })}`).catch(() => null);
  if (!tree || !panel.isConnected) return panel?.remove();
  const reporter = esc(state.reporter.countryName);
  const colors = ["#1f5f8b", "#31988b", "#d4a04c", "#7871a8", "#c87869", "#6c9cb8", "#849b66", "#a67b9b", "#537a88", "#b69461"];
  const path = [{ name: t("All imports"), valueUsd: tree.totalUsd, children: tree.sections }];
  const back = panel.querySelector("#category-back");
  const heading = panel.querySelector("#category-current");
  const list = panel.querySelector("#category-list");
  const pick = panel.querySelector("#category-pick");
  const plot = chart(panel.querySelector("#import-donut"), {
    color: colors,
    tooltip: {
      formatter: (p) => `<b>${esc(p.data.code)}</b> ${esc(p.name)}<br>${t("{value}, {share} of the imports of {reporter}", { value: usd(p.value), share: pct(p.value / tree.totalUsd), reporter })}`,
    },
    series: [{
      type: "pie", radius: ["57%", "86%"], center: ["50%", "50%"],
      itemStyle: { borderColor: css("--surface"), borderWidth: 2, borderRadius: 5 },
      label: { show: false }, labelLine: { show: false },
      emphasis: { scaleSize: 5, itemStyle: { shadowBlur: 12, shadowColor: "#14213d20" } },
    }],
  });
  const open = (i) => {
    const item = path.at(-1).children[i];
    if (!item.children.length) return (location.hash = `#/product/${item.code}?year=${tree.year}`);
    path.push(item);
    draw();
  };
  const draw = () => {
    const current = path.at(-1);
    back.disabled = path.length === 1;
    heading.textContent = path.map((n) => n.code ?? n.name).join(" / ");
    heading.title = current.name;
    pick.innerHTML = /^\d{2}(\d{2})?$/.test(current.code ?? "")
      ? `<a href="#/product/${current.code}?year=${tree.year}">${t("Where {reporter} gets {name}", { reporter, name: esc(current.name) })} →</a>` : "";
    plot.setOption({
      title: {
        text: usd(current.valueUsd), subtext: path.length === 1 ? t("All imports") : `${t("HS")} ${current.code}`,
        left: "center", top: "40%", itemGap: 8,
        textStyle: { fontSize: 28, fontWeight: 500, color: css("--ink"), fontFamily: css("--font") },
        subtextStyle: { fontSize: 12, color: css("--muted"), fontFamily: css("--font") },
      },
      series: [{ data: current.children.map((n, i) => ({ name: n.name, code: n.code, value: n.valueUsd, itemStyle: { color: colors[i % colors.length] } })) }],
    });
    list.replaceChildren(html(current.children.map((n, i) => `<button type="button" class="category-row" data-index="${i}" title="${esc(n.code)} ${esc(n.name)}">
      <span class="category-swatch" style="background:${colors[i % colors.length]}"></span>
      <span class="category-name"><span class="code">${esc(n.code)}</span> ${esc(n.name)}</span>
      <span class="category-value">${usd(n.valueUsd)}<small>${pct(current.valueUsd ? n.valueUsd / current.valueUsd : 0)}</small></span>
      <span class="category-arrow" aria-hidden="true">›</span></button>`).join("")));
    list.scrollTop = 0;
  };
  list.addEventListener("click", (event) => {
    const row = event.target.closest("[data-index]");
    if (row) open(Number(row.dataset.index));
  });
  const highlight = (event) => {
    const row = event.target.closest("[data-index]");
    plot.dispatchAction({ type: "downplay", seriesIndex: 0 });
    if (row) plot.dispatchAction({ type: "highlight", seriesIndex: 0, dataIndex: Number(row.dataset.index) });
  };
  list.addEventListener("mouseover", highlight);
  list.addEventListener("focusin", highlight);
  list.addEventListener("mouseleave", () => plot.dispatchAction({ type: "downplay", seriesIndex: 0 }));
  list.addEventListener("focusout", () => plot.dispatchAction({ type: "downplay", seriesIndex: 0 }));
  back.addEventListener("click", () => {
    if (path.length > 1) path.pop();
    draw();
  });
  plot.on("click", (p) => Number.isInteger(p.dataIndex) && open(p.dataIndex));
  draw();
}

export default async function overview(root, _, params) {
  const minValue = Number(params.get("minValue") ?? 1_000_000);
  const data = await api(`/overview?${scoped({ year: params.get("year"), minValue })}`);
  const earlier = state.snapshot.years.filter((y) => y < data.year);
  const from = earlier.includes(Number(params.get("from"))) ? Number(params.get("from")) : earlier[0];
  const moved = from && await api(`/movers?${scoped({ from, to: data.year, minValue })}`);
  const reporter = esc(state.reporter.countryName);
  const rows = data.rows.map((r) => ({
    code: r.productCode,
    description: r.description,
    total: r.metrics.totalUsd,
    suppliers: r.metrics.supplierCount,
    top: r.metrics.topSupplier?.countryName,
    topShare: r.metrics.topSupplier?.share,
    top3: r.metrics.top3Share,
    hhi: r.metrics.hhi,
    worldHhi: r.world?.hhi,
    worldTop: r.world?.topSupplier?.countryName,
  }));

  root.append(html(`
    <div class="head">
      <h1>${t("Imports of {reporter} by supplier concentration, {year}", { reporter, year: data.year })}</h1>
      <p class="lede">${t("Each HS6 product {reporter} imported in {year}, with how much of its value came from the largest supplier, the three largest, and the Herfindahl-Hirschman index (0 to 1, where 1 means a single supplier). Click a product to investigate it.", { reporter, year: data.year })}</p>
      <form class="controls">
        <label>${t("Year")} <select name="year">${state.snapshot.years
          .map((y) => `<option ${y === data.year ? "selected" : ""}>${y}</option>`).reverse().join("")}</select></label>
        <label>${t("Minimum import value")} <select name="minValue">${THRESHOLDS
          .map((v) => `<option value="${v}" ${v === minValue ? "selected" : ""}>${v ? t("{value} or more", { value: usd(v) }) : t("Any")}</option>`)
          .join("")}</select></label>
        <label>${t("Search")} <input name="search" type="search" placeholder="${t("Code or description")}"></label>
      </form>
    </div>
    ${state.snapshot.categories ? `<div class="panel" id="categories">
      <h2>${t("What {reporter} imports, from sections to products, {year}", { reporter, year: data.year })} ${storeTag("MongoDB documents")}</h2>
      <p>${t("Every import of {reporter} in {year}, grouped by HS section. Select a slice or a row to explore chapters, headings and products. Shares in the list refer to the current group.", { reporter, year: data.year })}</p>
      <div class="category-nav"><button type="button" id="category-back" disabled>← ${t("Back")}</button><span id="category-current" aria-live="polite"></span></div>
      <div class="import-mix"><div class="chart" id="import-donut"></div><div class="category-list" id="category-list" aria-label="${t("Import categories")}"></div></div>
      <p id="category-pick"></p></div>` : ""}
    <div class="panel">
      <h2>${t("Choice or structure?")}</h2>
      <p>${t("Supplier concentration of {reporter} against the concentration of world exports of the same product, both from BACI {year}. Products high on the left depend on few suppliers although the world market offers many. Products on the right are concentrated because few countries export them at all. Bubble size follows import value.", { reporter, year: data.year })}</p>
      <div class="chart tall" id="quadrant"></div>
    </div>
    ${moved ? `<div class="panel">
      <h2>${t("Biggest shifts in concentration, {from} to {to}", { from, to: data.year })}</h2>
      <p>${t("Among the {count} products imported in both years at the minimum value or more, the ten whose supplier HHI rose the most and the ten where it fell the most. The hollow dot is {from}, the solid dot {to}, and red marks a rise.", { count: count(moved.compared), from, to: data.year })}</p>
      <form class="controls"><label>${t("Compare with")} <select name="from">${earlier
        .map((y) => `<option ${y === from ? "selected" : ""}>${y}</option>`).join("")}</select></label></form>
      <div class="chart tall" id="movers"></div>
    </div>` : ""}
    <div class="panel"><h2>${rows.length === 1 ? t("1 product") : t("{count} products", { count: count(rows.length) })} ${storeTag("MongoDB documents")}</h2><div id="products"></div></div>
  `));

  const form = root.querySelector("form");
  form.addEventListener("change", (event) => {
    if (event.target.name === "search") return;
    location.hash = `#/overview?${query({ year: form.year.value, minValue: form.minValue.value, from: params.get("from") })}`;
  });

  const grid = table(root.querySelector("#products"), {
    data: rows,
    selectableRows: false,
    initialSort: [{ column: "total", dir: "desc" }],
    columns: [
      { title: t("Code"), field: "code", width: 90, cssClass: "code" },
      { title: t("Product"), field: "description", minWidth: 240, formatter: "plaintext", tooltip: true },
      usdColumn(t("Imports"), "total", { width: 120 }),
      { title: t("Suppliers"), field: "suppliers", hozAlign: "right", sorter: "number", width: 110 },
      { title: t("Largest supplier"), field: "top", width: 160 },
      pctColumn(t("Its share"), "topShare", { width: 100 }),
      pctColumn(t("Top 3"), "top3", { width: 90 }),
      indexColumn(t("HHI"), "hhi", { width: 90 }),
      indexColumn(t("World HHI"), "worldHhi", { width: 120 }),
    ],
  });
  grid.on("rowClick", (_, row) => (location.hash = `#/product/${row.getData().code}?year=${data.year}`));
  form.search.addEventListener("input", () => {
    const term = form.search.value.trim().toLowerCase();
    grid.setFilter(term ? (r) => r.code.startsWith(term) || r.description.toLowerCase().includes(term) : []);
  });

  const maxTotal = Math.max(...rows.map((r) => r.total), 1);
  const quadrant = chart(root.querySelector("#quadrant"), {
    media: [{ query: { maxWidth: 360 }, option: { series: [{ markArea: { label: { show: false } } }] } },
      { option: { series: [{ markArea: { label: { show: true } } }] } }],
    grid: { left: 60, right: 30, top: 30, bottom: 55 },
    tooltip: {
      formatter: ({ data: [x, y, , r] }) => `<b>${esc(r.code)}</b> ${esc(r.description)}<br>
        ${t("Imports {value}, largest supplier {name} ({share})", { value: usd(r.total), name: esc(r.top), share: pct(r.topShare) })}<br>
        ${t("Supplier HHI {hhi}, world HHI {world}, largest exporter {name}", { hhi: index(y), world: index(x), name: esc(r.worldTop) })}`,
    },
    xAxis: { ...axis(), name: t("World exporter HHI"), nameLocation: "middle", nameGap: 32, min: 0, max: 1 },
    yAxis: { ...axis(), name: t("Supplier HHI"), nameLocation: "middle", nameGap: 42, min: 0, max: 1 },
    series: [{
      type: "scatter",
      data: rows.filter((r) => r.hhi != null && r.worldHhi != null).map((r) => [r.worldHhi, r.hhi, r.total, r]),
      symbolSize: (d) => 4 + 30 * Math.sqrt(d[2] / maxTotal),
      itemStyle: { color: (p) => (p.data[1] >= HIGH && p.data[0] < HIGH ? css("--warn") : css("--accent")), opacity: 0.65 },
      markLine: {
        silent: true,
        symbol: "none",
        lineStyle: { color: css("--muted"), type: "dashed" },
        label: { show: false },
        data: [{ xAxis: HIGH }, { yAxis: HIGH }, [{ coord: [0, 0] }, { coord: [1, 1] }]],
      },
      markArea: {
        silent: true,
        itemStyle: { color: "transparent" },
        label: { color: css("--muted"), fontSize: 11, overflow: "break", lineHeight: 16 },
        data: [
          [{ name: t("Few suppliers, open world market"), coord: [0, 1], label: { position: "insideTopLeft", width: 100 } }, { coord: [HIGH, HIGH] }],
          [{ name: t("Few suppliers, few exporters"), coord: [HIGH, 1], label: { position: "insideTopRight", width: 120 } }, { coord: [1, HIGH] }],
        ],
      },
    }],
  });
  quadrant.on("click", (p) => (location.hash = `#/product/${p.data[3].code}?year=${data.year}`));

  if (state.snapshot.categories) categories(root.querySelector("#categories"), data.year);
  if (moved) movers(root, moved, params);
  await twins(root, "imports");
}

function movers(root, moved, params) {
  root.querySelector("select[name=from]").addEventListener("change", (e) => {
    params.set("from", e.target.value);
    location.hash = `#/overview?${params}`;
  });
  const rows = [...moved.rising, ...moved.falling];
  const label = (r) => `${r.productCode} ${r.description}`;
  const supplier = (m) => (m.topSupplier ? `${esc(m.topSupplier.countryName)} ${pct(m.topSupplier.share)}` : t("n/a"));
  const dot = (r, side) => ({ value: [r[side].hhi, label(r)], row: r });
  const node = root.querySelector("#movers");
  const plot = chart(node, {
    grid: { left: Math.min(240, node.clientWidth * 0.4), right: 20, top: 10, bottom: 40 },
    tooltip: {
      formatter: ({ data: { row: r } }) => `<b>${esc(r.productCode)}</b> ${esc(r.description)}<br>
        ${moved.from}: ${t("HHI")} ${index(r.from.hhi)}, ${supplier(r.from)}<br>
        ${moved.to}: ${t("HHI")} ${index(r.to.hhi)}, ${supplier(r.to)}`,
    },
    xAxis: { ...axis(), name: t("Supplier HHI"), nameLocation: "middle", nameGap: 26, min: 0, max: 1 },
    yAxis: { ...axis(), type: "category", inverse: true, data: rows.map(label),
      axisLabel: { color: css("--muted"), width: Math.min(230, node.clientWidth * 0.4 - 10), overflow: "truncate" } },
    series: [
      {
        type: "lines", coordinateSystem: "cartesian2d", silent: true,
        data: rows.map((r) => ({ coords: [[r.from.hhi, label(r)], [r.to.hhi, label(r)]], lineStyle: { color: css(r.change > 0 ? "--warn" : "--accent"), width: 2, opacity: 0.6 } })),
      },
      { type: "scatter", symbolSize: 9, data: rows.map((r) => dot(r, "from")), itemStyle: { color: css("--surface"), borderColor: css("--muted"), borderWidth: 1.5 } },
      { type: "scatter", symbolSize: 10, data: rows.map((r) => ({ ...dot(r, "to"), itemStyle: { color: css(r.change > 0 ? "--warn" : "--accent") } })) },
    ],
  });
  plot.on("click", (p) => p.data?.row && (location.hash = `#/product/${p.data.row.productCode}?year=${moved.to}`));
}
