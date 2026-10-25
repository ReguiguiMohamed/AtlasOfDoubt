import { lang, t } from "../i18n.js";
import { api, axis, chart, css, esc, html, index, indexColumn, kpi, pct, pctColumn, query, scoped, state, storeTag, table, usd, usdColumn } from "../lib.js";
import { loadWorld, shapeId, worldMap } from "../map.js";

const signed = new Intl.NumberFormat(lang, { minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: "exceptZero" });
const score = (v) => (v == null ? t("n/a") : signed.format(v));

export default async function balance(root, _, params) {
  const data = await api(`/balance?${scoped({ year: params.get("year") })}`);
  const reporter = esc(state.reporter.countryName);
  const { overall } = data;
  const years = data.years.map((y) => String(y.year));
  const ranked = [...data.partners].sort((a, b) => a.balanceUsd - b.balanceUsd);
  const deficit = ranked[0]?.balanceUsd < 0 ? ranked[0] : null;
  const surplus = ranked.at(-1)?.balanceUsd > 0 ? ranked.at(-1) : null;
  const sections = data.sections.filter((s) => s.lafay != null).reverse();
  const sectionName = (s) => (s.name ? `${s.code} ${s.name}` : `HS ${s.code}`);

  root.append(html(`
    <div class="head">
      <h1>${t("Trade balance of {reporter}, {year}", { reporter, year: data.year })}</h1>
      <p class="lede">${t("What {reporter} sells against what it buys: with each partner, in each HS section and across the years. A partner's purchases from {reporter} and its sales to it come from the same reconciled BACI flows.", { reporter })}</p>
      <form class="controls">
        <label>${t("Year")} <select name="year">${state.snapshot.years
          .map((y) => `<option ${y === data.year ? "selected" : ""}>${y}</option>`).reverse().join("")}</select></label>
      </form>
    </div>
    <div class="kpis">
      ${kpi(t("Trade balance"), usd(overall.balanceUsd), t("{exports} exported, {imports} imported", { exports: usd(overall.exportsUsd), imports: usd(overall.importsUsd) }))}
      ${kpi(t("Coverage ratio"), pct(overall.coverage, 0), t("Exports as a share of imports"))}
      ${kpi(t("Normalized balance"), score(overall.normalized), t("-1 only imports, 1 only exports"))}
      ${kpi(t("Grubel-Lloyd index"), index(overall.grubelLloyd), t("Share of trade within the same products"))}
      ${surplus ? kpi(t("Largest surplus"), esc(surplus.countryName), usd(surplus.balanceUsd)) : ""}
      ${deficit ? kpi(t("Largest deficit"), esc(deficit.countryName), usd(deficit.balanceUsd)) : ""}
    </div>
    <div class="panel"><h2>${t("Balance with each partner, {year}", { year: data.year })} ${storeTag("MongoDB documents")}</h2>
      <p>${t("Each country is colored by its normalized balance with {reporter}, the balance over the trade of the pair. Red is a deficit for {reporter}, green a surplus.", { reporter })}</p>
      <p class="map-key"><span><i style="background:var(--ink)"></i>${reporter}</span></p>
      <div class="chart map" id="balance-map"></div></div>
    <div class="grid">
      <div class="panel"><h2>${t("Exports, imports and balance, {from} to {to}", { from: years[0], to: years.at(-1) })}</h2><div class="chart" id="trend"></div></div>
      <div class="panel"><h2>${t("Lafay index by HS section, {year}", { year: data.year })}</h2>
        <p>${t("A section's balance minus the share of the overall balance its trade would carry, in percent of total trade. The indices add to zero, so a section above zero is a strength whatever the overall balance.")}</p>
        <div class="chart tall" id="lafay"></div></div>
    </div>
    <div class="panel" style="margin-top:1.25rem"><h2>${t("Partner table")}</h2>
      <p>${t("Trade intensity above 1 means {reporter} sends the partner a larger share of its exports than the partner's share of world imports.", { reporter })}</p>
      <div id="partners"></div></div>
  `));

  const form = root.querySelector("form");
  form.addEventListener("change", () => (location.hash = `#/balance?${query({ year: form.year.value })}`));
  const profile = (code) => code && (location.hash = `#/country/${code}?year=${data.year}`);

  const node = root.querySelector("#balance-map");
  loadWorld()
    .then(() => node.isConnected && worldMap(node, {
      tooltip: { formatter: (p) => (p.data?.partner
        ? `<b>${esc(p.data.partner.countryName)}</b><br>${t("Balance")}: ${usd(p.data.partner.balanceUsd)}<br>${t("Normalized balance")}: ${score(p.value)}`
        : p.name === shapeId(data.reporter.countryCode) ? `<b>${reporter}</b>` : "") },
      visualMap: { min: -1, max: 1, text: [t("Surplus"), t("Deficit")], inRange: { color: [css("--warn"), css("--land"), css("--sold")] } },
      // The visualMap clears the color of any data item without a value, so the reporter is painted as a region.
      geo: { emphasis: { label: { show: false }, itemStyle: { areaColor: css("--accent") } }, regions: [{ name: shapeId(data.reporter.countryCode), itemStyle: { areaColor: css("--ink") } }] },
      series: [{
        type: "map",
        data: data.partners.filter((p) => p.normalized != null).map((p) => ({ name: shapeId(p.countryCode), value: p.normalized, partner: p })),
      }],
    }).on("click", (p) => profile(p.data?.partner?.countryCode)))
    .catch(() => node.remove());

  chart(root.querySelector("#trend"), {
    grid: { left: 70, right: 20, top: 40, bottom: 30 },
    legend: { textStyle: { color: css("--muted") } },
    tooltip: { trigger: "axis", valueFormatter: usd },
    xAxis: { ...axis(), type: "category", data: years },
    yAxis: { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
    series: [
      { name: t("Exports"), type: "bar", stack: "flow", data: data.years.map((y) => y.exportsUsd), itemStyle: { color: css("--sold") } },
      { name: t("Imports"), type: "bar", stack: "flow", data: data.years.map((y) => (y.importsUsd == null ? null : -y.importsUsd)), itemStyle: { color: css("--warn") },
        tooltip: { valueFormatter: (v) => usd(v == null ? v : -v) } },
      { name: t("Balance"), type: "line", data: data.years.map((y) => y.balanceUsd ?? null), itemStyle: { color: css("--ink") } },
    ],
  });

  chart(root.querySelector("#lafay"), {
    grid: { left: 190, right: 50, top: 10, bottom: 30 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: ([p]) => {
      const s = sections[p.dataIndex];
      return `<b>${esc(sectionName(s))}</b><br>${t("Lafay index")}: ${score(s.lafay)}<br>${t("Balance")}: ${usd(s.balanceUsd)}<br>${t("Grubel-Lloyd index")}: ${index(s.grubelLloyd)}`;
    } },
    xAxis: { ...axis(), type: "value" },
    yAxis: { ...axis(), type: "category", data: sections.map(sectionName), axisLabel: { color: css("--muted"), width: 180, overflow: "truncate" } },
    series: [{
      type: "bar", barMaxWidth: 18,
      data: sections.map((s) => ({ value: s.lafay, itemStyle: { color: css(s.lafay < 0 ? "--warn" : "--sold") } })),
    }],
  });

  table(root.querySelector("#partners"), {
    data: data.partners,
    columns: [
      { title: t("Country"), field: "countryName", minWidth: 140 },
      { title: t("ISO"), field: "isoCode", width: 70 },
      usdColumn(t("Exports"), "exportsUsd"),
      usdColumn(t("Imports"), "importsUsd"),
      usdColumn(t("Balance"), "balanceUsd"),
      { title: t("Normalized balance"), field: "normalized", hozAlign: "right", sorter: "number", formatter: (c) => score(c.getValue()) },
      pctColumn(t("Coverage ratio"), "coverage"),
      indexColumn(t("Trade intensity"), "intensity"),
    ],
  }).on("rowClick", (_, row) => profile(row.getData().countryCode));
}
