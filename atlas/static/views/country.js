import { t } from "../i18n.js";
import { api, axis, chart, count, css, esc, html, index, kpi, pct, pctColumn, query, state, table, usd, usdColumn } from "../lib.js";

export default async function country(root, [code], params) {
  if (!code) return list(root);
  const wanted = Number(params.get("year")) || undefined;
  const data = await api(`/countries/${code}?${query({ snapshot: state.snapshot._id, year: wanted })}`);
  const name = data.country.countryName;
  const recorded = data.years.filter((y) => y.valueUsd != null);
  if (!recorded.length) {
    root.append(html(`<div class="head"><h1>${esc(name)}</h1>
      <p class="notice">${t("BACI records no exports from {name} to Tunisia between {from} and {to}.", { name: esc(name), from: data.years[0].year, to: data.years.at(-1).year })}</p></div>`));
    return;
  }
  // Without a year in the link, open on the latest year this country actually supplied.
  if (!wanted && !data.products.length) return country(root, [code], new URLSearchParams({ year: recorded.at(-1).year }));
  const current = data.years.find((y) => y.year === data.year);
  const leads = data.products.filter((p) => p.rank === 1);
  const sole = leads.filter((p) => p.supplierCount === 1).length;

  root.append(html(`
    <div class="head">
      <h1><span class="code">${esc(data.country.isoCode)}</span> ${esc(name)}</h1>
      <p class="lede">${t("Everything Tunisia imported from {name}, product by product. Share and rank are measured among each product's suppliers.", { name: esc(name) })}</p>
      <form class="controls">
        <label>${t("Year")} <select name="year">${recorded
          .map((y) => `<option ${y.year === data.year ? "selected" : ""}>${y.year}</option>`).reverse().join("")}</select></label>
        <a href="#/scenario?${query({ mode: "country", suppliers: code, year: data.year, reduction: 100 })}"><button type="button" class="primary">${t("Simulate losing this supplier")}</button></a>
      </form>
    </div>
    <div class="kpis">
      ${kpi(t("Supplied to Tunisia"), usd(current.valueUsd), String(data.year))}
      ${kpi(t("Share of all Tunisian imports"), pct(current.shareOfImports))}
      ${kpi(t("Products"), count(data.products.length))}
      ${kpi(t("Products it leads"), count(leads.length), sole ? t("{count} as sole supplier", { count: count(sole) }) : "")}
    </div>
    <div class="panel"><h2>${t("Supplies to Tunisia, {from} to {to}", { from: data.years[0].year, to: data.years.at(-1).year })}</h2>
      <div class="chart" id="trend"></div></div>
    <div class="panel"><h2>${t("Products from {name}, {year}", { name: esc(name), year: data.year })}</h2>
      <p>${t("Sort by share to find the products where Tunisia depends most on {name}.", { name: esc(name) })}</p>
      <div id="products"></div></div>
  `));

  root.querySelector("select[name=year]").addEventListener("change", (e) => {
    location.hash = `#/country/${code}?year=${e.target.value}`;
  });

  chart(root.querySelector("#trend"), {
    grid: { left: 70, right: 60, top: 40, bottom: 30 },
    legend: { textStyle: { color: css("--muted") } },
    tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? t("no recorded flow") : v > 1 ? usd(v) : pct(v)) },
    xAxis: { ...axis(), type: "category", data: data.years.map((y) => String(y.year)) },
    yAxis: [
      { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
      { ...axis(), type: "value", min: 0, splitLine: { show: false }, axisLabel: { color: css("--muted"), formatter: (v) => pct(v, 0) } },
    ],
    series: [
      { name: t("Supplied"), type: "bar", data: data.years.map((y) => y.valueUsd), itemStyle: { color: css("--accent-2") } },
      { name: t("Share of all Tunisian imports"), type: "line", yAxisIndex: 1, data: data.years.map((y) => y.shareOfImports), itemStyle: { color: css("--warn") } },
    ],
  });

  const products = table(root.querySelector("#products"), {
    data: data.products,
    paginationSize: 15,
    columns: [
      { title: t("Code"), field: "productCode", width: 90 },
      { title: t("Product"), field: "description", tooltip: true, minWidth: 200 },
      usdColumn(t("Supplied"), "valueUsd"),
      pctColumn(t("Share"), "share"),
      { title: t("Rank"), field: "rank", hozAlign: "right", sorter: "number", width: 100, formatter: (c) => t("{count} of {total}", { count: c.getValue(), total: c.getData().supplierCount }) },
      { title: t("HHI"), field: "hhi", hozAlign: "right", sorter: "number", width: 80, formatter: (c) => index(c.getValue()) },
    ],
  });
  products.on("rowClick", (_, row) => (location.hash = `#/product/${row.getData().productCode}?year=${data.year}`));
}

function list(root) {
  root.append(html(`
    <div class="head">
      <h1>${t("Supplier countries")}</h1>
      <p class="lede">${t("Pick a country to see what it sends Tunisia, how much of Tunisia's imports it carries, and the products where it leads.")}</p>
    </div>
    <div class="panel"><div id="countries"></div></div>
  `));
  const reporter = state.detail.reporter.countryCode;
  const countries = table(root.querySelector("#countries"), {
    data: state.detail.countries.filter((c) => c.countryCode !== reporter),
    paginationSize: 20,
    initialSort: [{ column: "countryName", dir: "asc" }],
    columns: [
      { title: t("Country"), field: "countryName", headerFilter: "input", headerFilterPlaceholder: t("Filter countries") },
      { title: t("ISO"), field: "isoCode", width: 90 },
    ],
  });
  countries.on("rowClick", (_, row) => (location.hash = `#/country/${row.getData().countryCode}`));
}
