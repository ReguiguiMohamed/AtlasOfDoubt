import { lang, t } from "../i18n.js";
import { api, axis, chart, css, esc, html, index, pct, relativeRanks, scoped, state, storeTag, unavailable } from "../lib.js";
import { loadWorld, shapeId, worldMap } from "../map.js";

// Shared products stack in rank order, and what the closest twins share beyond them fills the rest of the bar.
const SHARED_COLORS = ["--accent", "--sold", "--supply"];

// The trade twins of the reporter for one flow: a map of every country's similarity and the ten closest with what they share.
export default async function twins(root, flow) {
  if (!state.snapshot.twins) return;
  const data = await api(`/twins?${scoped({ flow })}`).catch((e) => e);
  if (!root.isConnected) return;
  const heading = `<h2>${t("Trade twins, {year}", { year: state.snapshot.twins.year })} ${storeTag("Milvus vectors")}</h2>`;
  if (data instanceof Error) {
    // A 404 means the reporter has no trade in the flow, and only a 503 means the store failed.
    if (data.status !== 503) return;
    root.append(html(`<div class="panel" style="margin-top:1.25rem">${heading}${unavailable("Milvus vectors")}</div>`).firstElementChild);
    return;
  }
  const reporter = esc(state.reporter.countryName);
  const closest = [...data.closest].reverse();
  const ranks = relativeRanks(data.similar.map((s) => s.similarity));
  const score = new Intl.NumberFormat(lang, { minimumFractionDigits: 3, maximumFractionDigits: 6 });
  const products = (s) => s.shared.map((p) => `${esc(p.productCode)} ${esc(p.description)}: ${pct(p.share)} / ${pct(p.twinShare)}`).join("<br>");
  const tip = (s) => `<b>${esc(s.countryName)}</b>: ${score.format(s.similarity)}` + (s.shared ? `<br>${t("{reporter} / twin share of {flow}", { reporter, flow: t(flow) })}<br>${products(s)}` : "");
  const panel = html(`<div class="panel" style="margin-top:1.25rem">${heading}
    <p>${t("The countries whose {flow} look most like those of {reporter}. Each basket is a sparse vector of square-rooted product shares in Milvus, so the score is the Bhattacharyya coefficient: 1 for the same mix, 0 when no product is shared. Each bar splits the score into the products the two share most. Twins trade alike and need not trade with each other.", { reporter, flow: t(flow) })}</p>
    <p class="map-key"><span><i></i>${esc(state.reporter.countryName)}</span> ${t("Colors show relative similarity rank. Hover for the actual score.")}</p>
    <div class="twins-layout"><div class="chart map" id="twins-map-${flow}"></div><div class="chart tall" id="twins-${flow}"></div></div></div>`).firstElementChild;
  root.append(panel);

  loadWorld()
    .then(() => panel.isConnected && worldMap(panel.querySelector(`#twins-map-${flow}`), {
      tooltip: { formatter: (p) => (p.data?.twin ? tip(p.data.twin) : p.data?.name === shapeId(data.reporter) ? `<b>${reporter}</b>` : "") },
      visualMap: { min: 0, max: 1, text: [t("More similar"), t("Less similar")], inRange: { color: ["#eaf2f7", "#7bb5b4", css("--accent")] } },
      geo: { emphasis: { label: { show: false }, itemStyle: { areaColor: css("--sold") } } },
      series: [{
        type: "map",
        data: [
          ...data.similar.map((s) => ({ name: shapeId(s.countryCode), value: ranks.get(s.similarity), twin: data.closest.find((c) => c.countryCode === s.countryCode) ?? s })),
          { name: shapeId(data.reporter), itemStyle: { areaColor: css("--warn") }, twin: null },
        ],
      }],
    }).on("click", (p) => p.data?.twin && (location.hash = `#/country/${p.data.twin.countryCode}`)))
    .catch(() => panel.querySelector(`#twins-map-${flow}`).remove());

  const part = (i) => closest.map((s) => s.shared[i]?.contribution ?? 0);
  chart(panel.querySelector(`#twins-${flow}`), {
    grid: { left: 110, right: 30, top: 20, bottom: 30 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: ([p]) => tip(closest[p.dataIndex]) },
    xAxis: { ...axis(), type: "value", min: 0, max: 1 },
    yAxis: { ...axis(), type: "category", data: closest.map((s) => s.countryName), axisLabel: { color: css("--muted"), width: 100, overflow: "truncate" } },
    series: [
      ...SHARED_COLORS.map((color, i) => ({
        type: "bar", stack: "score", data: part(i), itemStyle: { color: css(color) },
        label: i ? { show: false } : { show: true, position: "insideLeft", color: "#fff", fontSize: 10,
          formatter: (p) => p.value * (panel.querySelector(`#twins-${flow}`).clientWidth - 140) >= 44 ? closest[p.dataIndex].shared[0]?.productCode ?? "" : "" },
      })),
      {
        type: "bar", stack: "score", data: closest.map((s, n) => Math.max(0, s.similarity - SHARED_COLORS.reduce((a, _, i) => a + part(i)[n], 0))),
        itemStyle: { color: css("--line") },
        label: { show: true, position: "right", color: css("--ink"), formatter: (p) => index(closest[p.dataIndex].similarity) },
      },
    ],
  }).on("click", (p) => (location.hash = `#/country/${closest[p.dataIndex].countryCode}`));
}
