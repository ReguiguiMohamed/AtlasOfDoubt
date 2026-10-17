import { t } from "../i18n.js";
import { api, axis, chart, count, countryPicker, css, esc, html, index, kpi, pct, pctColumn, query, scoped, state, table, usd, usdColumn } from "../lib.js";

export default async function country(root, [code], params) {
  if (!code) return list(root);
  const wanted = Number(params.get("year")) || undefined;
  const data = await api(`/countries/${code}?${scoped({ year: wanted })}`);
  const name = data.country.countryName;
  const reporter = esc(state.reporter.countryName);
  const recorded = data.years.filter((y) => y.valueUsd != null || y.exportsUsd != null);
  if (!recorded.length) {
    root.append(html(`<div class="head"><h1>${esc(name)}</h1>
      <p class="notice">${t("BACI records no trade between {name} and {reporter} from {from} to {to}.", { name: esc(name), reporter, from: data.years[0].year, to: data.years.at(-1).year })}</p></div>`));
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
      <p class="lede">${t("Everything {reporter} imported from {name}, product by product. Share and rank are measured among each product's suppliers.", { name: esc(name), reporter })}</p>
      ${data.route ? `<p class="lede">${esc(t("Modelled sea route to {reporter}: {route}, {via}.", {
        reporter: state.reporter.countryName,
        route: t(data.route.name), via: data.route.via.length ? data.route.via.map((v) => t(v)).join(" → ") : t("no chokepoint"),
      }))} <a href="#/routes?${query({ select: data.route.id, year: data.year })}">${t("Sea routes")}</a></p>` : ""}
      <form class="controls">
        <label>${t("Year")} <select name="year">${recorded
          .map((y) => `<option ${y.year === data.year ? "selected" : ""}>${y.year}</option>`).reverse().join("")}</select></label>
        <a href="#/scenario?${query({ mode: "country", suppliers: code, year: data.year, reduction: 100 })}"><button type="button" class="primary">${t("Simulate losing this supplier")}</button></a>
      </form>
    </div>
    <div class="kpis">
      ${kpi(t("Supplied"), usd(current.valueUsd), String(data.year))}
      ${kpi(t("Share of all imports"), pct(current.shareOfImports))}
      ${kpi(t("Bought back"), usd(current.exportsUsd), t("{share} of all exports", { share: pct(current.shareOfExports) }))}
      ${kpi(t("Products"), count(data.products.length))}
      ${kpi(t("Products it leads"), count(leads.length), sole ? t("{count} as sole supplier", { count: count(sole) }) : "")}
    </div>
    <div class="panel"><h2>${t("Trade with {name}, {from} to {to}", { name: esc(name), from: data.years[0].year, to: data.years.at(-1).year })}</h2>
      <div class="chart" id="trend"></div></div>
    <div class="panel"><h2>${t("Products from {name}, {year}", { name: esc(name), year: data.year })}</h2>
      <p>${t("Sort by share to find the products where {reporter} depends most on {name}.", { name: esc(name), reporter })}</p>
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
      { name: t("Bought back"), type: "bar", data: data.years.map((y) => y.exportsUsd), itemStyle: { color: css("--accent") } },
      { name: t("Share of all imports"), type: "line", yAxisIndex: 1, data: data.years.map((y) => y.shareOfImports), itemStyle: { color: css("--warn") } },
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
      <h1>${t("Partner countries")}</h1>
      <p class="lede">${t("Pick a partner to see what it supplies, how much of all imports it carries, the products where it leads, and what it buys back.")}</p>
    </div>
    <div class="panel" id="countries"></div>
  `));
  const partners = state.detail.countries.filter((c) => c.countryCode !== state.reporter.countryCode);
  countryPicker(root.querySelector("#countries"), partners, (c) => (location.hash = `#/country/${c.countryCode}`));
}
