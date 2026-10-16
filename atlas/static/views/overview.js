import { api, axis, chart, css, esc, html, index, indexColumn, pct, pctColumn, query, state, table, usd, usdColumn } from "../lib.js";

// 0.25 is where the 2010 US Horizontal Merger Guidelines start calling a market highly concentrated (HHI 2500 of 10000).
const HIGH = 0.25;
const THRESHOLDS = [0, 100_000, 1_000_000, 10_000_000, 100_000_000];

export default async function overview(root, _, params) {
  const minValue = Number(params.get("minValue") ?? 1_000_000);
  const data = await api(`/overview?${query({ snapshot: state.snapshot._id, year: params.get("year"), minValue })}`);
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
      <h1>Tunisian imports by supplier concentration, ${data.year}</h1>
      <p class="lede">Each HS6 product Tunisia imported in ${data.year}, with how much of its value came from the
        largest supplier, the three largest, and the Herfindahl-Hirschman index (0 to 1, where 1 means a single
        supplier). Click a product to investigate it.</p>
      <form class="controls">
        <label>Year <select name="year">${state.snapshot.years
          .map((y) => `<option ${y === data.year ? "selected" : ""}>${y}</option>`).reverse().join("")}</select></label>
        <label>Minimum import value <select name="minValue">${THRESHOLDS
          .map((t) => `<option value="${t}" ${t === minValue ? "selected" : ""}>${t ? `${usd(t)} or more` : "Any"}</option>`)
          .join("")}</select></label>
        <label>Search <input name="search" type="search" placeholder="Code or description"></label>
      </form>
    </div>
    <div class="panel">
      <h2>Choice or structure?</h2>
      <p>Tunisia's supplier concentration against the concentration of world exports of the same product, both
        from BACI ${esc(data.year)}. Products high on the left depend on few suppliers although the world market
        offers many. Products on the right are concentrated because few countries export them at all.
        Bubble size follows import value.</p>
      <div class="chart tall" id="quadrant"></div>
    </div>
    <div class="panel"><h2>${rows.length.toLocaleString("en")} products</h2><div id="products"></div></div>
  `));

  const form = root.querySelector("form");
  form.addEventListener("change", (event) => {
    if (event.target.name === "search") return;
    location.hash = `#/overview?${query({ year: form.year.value, minValue: form.minValue.value })}`;
  });

  const grid = table(root.querySelector("#products"), {
    data: rows,
    selectableRows: false,
    initialSort: [{ column: "total", dir: "desc" }],
    columns: [
      { title: "Code", field: "code", width: 90, cssClass: "code" },
      { title: "Product", field: "description", minWidth: 240, formatter: "plaintext", tooltip: true },
      usdColumn("Imports", "total", { width: 110 }),
      { title: "Suppliers", field: "suppliers", hozAlign: "right", sorter: "number", width: 100 },
      { title: "Largest supplier", field: "top", width: 150 },
      pctColumn("Its share", "topShare", { width: 100 }),
      pctColumn("Top 3", "top3", { width: 90 }),
      indexColumn("HHI", "hhi", { width: 90 }),
      indexColumn("World HHI", "worldHhi", { width: 110 }),
    ],
  });
  grid.on("rowClick", (_, row) => (location.hash = `#/product/${row.getData().code}?year=${data.year}`));
  form.search.addEventListener("input", () => {
    const term = form.search.value.trim().toLowerCase();
    grid.setFilter(term ? (r) => r.code.startsWith(term) || r.description.toLowerCase().includes(term) : []);
  });

  const maxTotal = Math.max(...rows.map((r) => r.total), 1);
  const quadrant = chart(root.querySelector("#quadrant"), {
    grid: { left: 60, right: 30, top: 30, bottom: 55 },
    tooltip: {
      formatter: ({ data: [x, y, , r] }) => `<b>${esc(r.code)}</b> ${esc(r.description)}<br>
        Imports ${usd(r.total)}, largest supplier ${esc(r.top)} (${pct(r.topShare)})<br>
        Tunisia HHI ${index(y)}, world HHI ${index(x)}, largest exporter ${esc(r.worldTop)}`,
    },
    xAxis: { ...axis(), name: "World exporter HHI", nameLocation: "middle", nameGap: 32, min: 0, max: 1 },
    yAxis: { ...axis(), name: "Tunisia supplier HHI", nameLocation: "middle", nameGap: 42, min: 0, max: 1 },
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
        label: { color: css("--muted"), fontSize: 12 },
        data: [
          [{ name: "Few suppliers, open world market", coord: [0, 1], label: { position: "insideTopLeft" } }, { coord: [HIGH, HIGH] }],
          [{ name: "Few suppliers, few exporters", coord: [HIGH, 1], label: { position: "insideTopRight" } }, { coord: [1, HIGH] }],
        ],
      },
    }],
  });
  quadrant.on("click", (p) => (location.hash = `#/product/${p.data[3].code}?year=${data.year}`));
}
