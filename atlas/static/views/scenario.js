import { lang, t } from "../i18n.js";
import { api, axis, chart, css, esc, html, km, loadWorld, pct, pctColumn, query, scoped, shapeId, state, table, usd, usdColumn, zoomable } from "../lib.js";

const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
const ids = (value) => (value ?? "").split(",").filter(Boolean);
const bounded = (value, low, high, fallback) => {
  const n = Number(value);
  return value == null || value === "" || !Number.isFinite(n) ? fallback : Math.min(high, Math.max(low, n));
};
const listed = (items) => new Intl.ListFormat(lang, { type: "conjunction" }).format(items);
const tenth = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });
const days = (v) => (v == null ? t("none") : t("{days} days", { days: tenth.format(v) }));
const hot = (text) => `<b>${esc(text)}</b>`;
const CAUSE = { embargo: "Embargo", region: "Ports shut", rerouted: "Rerouted", cutOff: "Cut off" };
const MEASURES = [["affectedUsd", "Hit"], ["reroutedUsd", "Arrives late"], ["strandedUsd", "Stranded"], ["replacedUsd", "Replaced"], ["gapUsd", "Gap"]];

// The link holds the whole shock, so a shared link opens on the same scenario.
export const scenarioLink = (spec) => `#/scenario?${query({
  year: spec.year, code: spec.productCode, chokepoints: spec.chokepoints.join(","), regions: spec.regions.join(","),
  suppliers: spec.suppliers.join(","), reduction: Math.round(Number(spec.reduction) * 100), weeks: spec.weeks,
  spare: Math.round(Number(spec.spare) * 100), preset: spec.preset,
})}`;

export function shockName(spec, r, presets) {
  const preset = presets.find((p) => p.id === spec.preset);
  if (preset) return t(preset.name);
  const country = (code) => state.detail.countries.find((c) => c.countryCode === code)?.countryName ?? String(code);
  const text = listed([
    ...r.closed.map((c) => t("{strait} closed", { strait: t(c.name) })),
    ...spec.regions.map((id) => t("ports of {region} shut", { region: t(r.routes.find((x) => x.id === id)?.name ?? id) })),
    ...spec.suppliers.map((code) => t("embargo on {country}", { country: country(code) })),
  ]);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const shockTerms = (spec) => t("{year}, {weeks} weeks, severity {severity}, spare capacity elsewhere {spare}", {
  year: spec.year, weeks: spec.weeks, severity: pct(Number(spec.reduction), 0), spare: pct(Number(spec.spare), 0),
});

export default async function scenario(root, _, params) {
  const reporter = state.reporter;
  const years = [...state.snapshot.years].reverse();
  const asked = Number(params.get("year"));
  const spec = {
    snapshot: state.snapshot._id,
    reporter: reporter.countryCode,
    year: years.includes(asked) ? asked : years[0],
    productCode: params.get("code") || null,
    chokepoints: ids(params.get("chokepoints")),
    regions: ids(params.get("regions")),
    suppliers: ids(params.get("suppliers")).map(Number),
    reduction: bounded(params.get("reduction"), 0, 100, 100) / 100,
    weeks: bounded(params.get("weeks"), 1, 52, 52),
    spare: bounded(params.get("spare"), 0, 50, 10) / 100,
    preset: params.get("preset"),
  };
  const lanesOf = (year) => api(`/routes?${scoped({ year })}`);
  let [presets, lanes] = await Promise.all([api(`/scenarios/presets?${query({ snapshot: spec.snapshot })}`), lanesOf(spec.year)]);
  if (!presets.some((p) => p.id === spec.preset)) spec.preset = null;
  const byCode = new Map(state.detail.countries.map((c) => [c.countryCode, c]));
  const others = state.detail.countries
    .filter((c) => c.countryCode !== reporter.countryCode)
    .sort((a, b) => a.countryName.localeCompare(b.countryName, lang));
  spec.suppliers = spec.suppliers.filter((code) => byCode.has(code) && code !== reporter.countryCode);

  root.append(html(`
    <div class="head">
      <h1>${t("Disruption scenario")}</h1>
      <p class="lede">${t("Close a strait, shut the ports of a region or stop the exports of a country, and see what happens to the imports of {reporter}. Ships with another lane take it and arrive late. Of what is stranded, the exporters the shock spares make up a part, and the rest is the gap.", { reporter: esc(reporter.countryName) })}</p>
    </div>
    <div class="panel"><h2>${t("Real events and stress tests")}</h2>
      <p>${t("Each card loads a shock that happened, or one analysts test for, and runs it on the trade of {reporter}.", { reporter: esc(reporter.countryName) })}</p>
      <div class="events" id="events"></div></div>
    <form class="panel builder" id="shock">
      <h2>${t("Build your own shock")}</h2>
      <fieldset><legend>${t("Close a strait")}</legend><div class="chips" id="straits"></div></fieldset>
      <fieldset><legend>${t("Shut the ports of a region")}</legend><div class="chips" id="regions"></div></fieldset>
      <fieldset><legend>${t("Stop the exports of a country")}</legend>
        <div class="chips" id="embargo"><input name="country" list="countries" placeholder="${t("Type a country")}" autocomplete="off"></div>
        <datalist id="countries">${others.map((c) => `<option value="${esc(c.countryName)}">`).join("")}</datalist></fieldset>
      <div class="controls">
        <label>${t("HS code, optional")} <input name="code" value="${esc(spec.productCode ?? "")}" placeholder="10, 2709, 854231" pattern="(\\d{2}){1,3}" size="12"></label>
        <label>${t("Year")} <select name="year">${years.map((y) => `<option ${y === spec.year ? "selected" : ""}>${y}</option>`).join("")}</select></label>
        <label>${t("Severity")} <span><input name="reduction" type="range" min="0" max="100" step="5"> <output></output></span></label>
        <label>${t("Duration")} <span><input name="weeks" type="range" min="1" max="52"> <output></output></span></label>
        <label>${t("Spare capacity elsewhere")} <span><input name="spare" type="range" min="0" max="50" step="5"> <output></output></span></label>
      </div>
    </form>
    <div id="outcome">
      <p class="empty" id="idle">${t("Pick a card, or close a strait, shut a region or stop a country.")}</p>
      <p class="running" id="running" hidden>${t("Running the shock through every supplier and lane...")}</p>
      <div class="controls actions" id="actions" hidden>
        <button type="button" id="pin">${t("Pin as A to compare")}</button>
        <button type="button" id="share">${t("Copy link")}</button>
        <form id="save" class="controls"><label>${t("Report title")} <input name="title" required maxlength="200" size="34" placeholder="${t("What this scenario asks")}"></label>
          <button class="primary">${t("Save evidence report")}</button></form>
      </div>
      <div class="panel compare" id="compare" hidden>
        <h2>${t("A against B")}</h2><p id="versus"></p>
        <div class="kpis" id="deltas"></div>
        <div class="chart" id="pair"></div>
        <button type="button" id="unpin">${t("Unpin A")}</button>
      </div>
      <div id="result" hidden></div>
    </div>`));

  const form = root.querySelector("#shock");
  const events = root.querySelector("#events");
  const embargo = root.querySelector("#embargo");
  const idle = root.querySelector("#idle");
  const running = root.querySelector("#running");
  const actions = root.querySelector("#actions");
  const resultNode = root.querySelector("#result");
  const show = resultView(resultNode, reporter);

  const strait = (id) => t(lanes.chokepoints.find((c) => c.id === id)?.name ?? id);
  events.innerHTML = presets.map((p) => {
    const empty = !p.chokepoints?.length && !p.suppliers.length;
    const what = [...(p.chokepoints ?? []).map(strait), ...p.suppliers.map((c) => byCode.get(c)?.countryName), p.productCode && `HS ${p.productCode}`];
    return `<article class="event ${p.kind}" data-id="${p.id}">
      <span class="tag">${esc(p.kind === "observed" ? t("Happened, {when}", { when: t(p.when) }) : t("Stress test"))}</span>
      <h3>${esc(t(p.name))}</h3>
      <p>${esc(t(p.fact))}</p>
      <p class="terms">${esc(listed(what.filter(Boolean)))}. ${esc(t("{share} of traffic for {weeks} weeks", { share: pct(Number(p.reduction), 0), weeks: p.weeks }))}</p>
      <footer>${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.source)}</a>` : `<span>${t("A what-if, with no single source")}</span>`}
        <button type="button" class="primary" ${empty ? "disabled" : ""}>${t(empty ? "Not in this snapshot" : "Run it")}</button></footer>
    </article>`;
  }).join("");

  const chip = (kind, id, label, note) => `<button type="button" class="chip" data-kind="${kind}" data-id="${esc(id)}"
    aria-pressed="${spec[kind].includes(id)}">${esc(label)}${note ? ` <small>${esc(note)}</small>` : ""}</button>`;
  function drawChips() {
    const byValue = (a, b) => b.valueUsd - a.valueUsd;
    root.querySelector("#straits").innerHTML = [...lanes.chokepoints].sort(byValue).map((c) => chip("chokepoints", c.id, t(c.name), usd(c.valueUsd))).join("");
    root.querySelector("#regions").innerHTML = [...lanes.routes].sort(byValue).map((r) => chip("regions", r.id, t(r.name), usd(r.valueUsd))).join("");
    embargo.querySelectorAll(".chip").forEach((n) => n.remove());
    embargo.insertAdjacentHTML("afterbegin", spec.suppliers.map((code) => chip("suppliers", code, byCode.get(code).countryName, "×")).join(""));
  }

  const outputs = {
    reduction: (v) => pct(v / 100, 0),
    weeks: (v) => t("{weeks} weeks", { weeks: v }),
    spare: (v) => pct(v / 100, 0),
  };
  function syncForm() {
    form.code.value = spec.productCode ?? "";
    form.year.value = spec.year;
    form.reduction.value = Math.round(spec.reduction * 100);
    form.weeks.value = spec.weeks;
    form.spare.value = Math.round(spec.spare * 100);
    for (const [name, format] of Object.entries(outputs)) form[name].nextElementSibling.textContent = format(form[name].value);
  }

  const body = () => ({ ...spec, reduction: String(spec.reduction), spare: String(spec.spare) });
  let ticket = 0;
  let timer;
  let last = null;
  let pinned = null;
  const later = () => {
    clearTimeout(timer);
    timer = setTimeout(go, 250);
  };
  async function go() {
    history.replaceState(null, "", scenarioLink(spec));
    events.querySelectorAll(".event").forEach((e) => e.classList.toggle("active", e.dataset.id === spec.preset));
    const mine = ++ticket;
    if (!spec.chokepoints.length && !spec.regions.length && !spec.suppliers.length) {
      idle.textContent = t("Pick a card, or close a strait, shut a region or stop a country.");
      [idle.hidden, actions.hidden, running.hidden] = [false, true, true];
      resultNode.classList.add("stale");
      return;
    }
    running.hidden = false;
    root.querySelector("#outcome").classList.add("busy");
    try {
      const sent = body();
      const { result } = await api("/scenarios/preview", { method: "POST", body: JSON.stringify(sent) });
      if (mine !== ticket || !root.isConnected) return;
      last = { spec: sent, result, name: shockName(sent, result, presets) };
      [idle.hidden, resultNode.hidden, actions.hidden] = [true, false, false];
      resultNode.classList.remove("stale");
      show(sent, result, last.name);
      drawCompare();
    } catch (error) {
      if (mine !== ticket) return;
      idle.innerHTML = `<span class="error">${esc(error.message)}</span>`;
      [idle.hidden, actions.hidden] = [false, true];
      resultNode.classList.add("stale");
    } finally {
      if (mine === ticket) {
        running.hidden = true;
        root.querySelector("#outcome").classList.remove("busy");
      }
    }
  }

  events.addEventListener("click", (e) => {
    const card = e.target.closest(".event");
    const preset = presets.find((p) => p.id === card?.dataset.id);
    if (!preset || e.target.closest("a") || card.querySelector("button").disabled) return;
    Object.assign(spec, {
      chokepoints: [...(preset.chokepoints ?? [])], regions: [], suppliers: [...preset.suppliers],
      productCode: preset.productCode ?? null, reduction: Number(preset.reduction), weeks: preset.weeks, preset: preset.id,
    });
    syncForm();
    drawChips();
    later();
    root.querySelector("#outcome").scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
  });

  form.addEventListener("click", (e) => {
    const button = e.target.closest(".chip");
    if (!button) return;
    const { kind } = button.dataset;
    const id = kind === "suppliers" ? Number(button.dataset.id) : button.dataset.id;
    spec[kind] = spec[kind].includes(id) ? spec[kind].filter((x) => x !== id) : [...spec[kind], id];
    spec.preset = null;
    drawChips();
    later();
  });
  form.addEventListener("input", (e) => {
    const { name, value } = e.target;
    if (!outputs[name]) return;
    e.target.nextElementSibling.textContent = outputs[name](value);
    spec[name] = name === "weeks" ? Number(value) : Number(value) / 100;
    spec.preset = null;
    later();
  });
  form.addEventListener("change", async (e) => {
    const { name, value } = e.target;
    if (name === "country") {
      const term = value.trim().toLowerCase();
      const country = others.find((c) => c.countryName.toLowerCase() === term || c.isoCode?.toLowerCase() === term);
      if (!country) return;
      e.target.value = "";
      if (!spec.suppliers.includes(country.countryCode)) spec.suppliers = [...spec.suppliers, country.countryCode];
    } else if (name === "code") {
      if (!e.target.checkValidity()) return;
      spec.productCode = value.trim() || null;
    } else if (name === "year") {
      spec.year = Number(value);
      lanes = await lanesOf(spec.year);
    } else return;
    spec.preset = null;
    drawChips();
    later();
  });
  form.addEventListener("submit", (e) => e.preventDefault());

  root.querySelector("#share").addEventListener("click", async (e) => {
    await navigator.clipboard?.writeText(location.href).catch(() => {});
    e.target.textContent = t("Link copied");
  });
  const save = root.querySelector("#save");
  save.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.querySelector("button").disabled = true;
    try {
      const { id } = await api("/reports", { method: "POST", body: JSON.stringify({ ...last.spec, title: save.elements.title.value.trim() }) });
      location.hash = `#/reports/${id}`;
    } catch (error) {
      save.querySelector("button").disabled = false;
      save.insertAdjacentHTML("beforeend", `<p class="error">${esc(error.message)}</p>`);
    }
  });

  let pair;
  const compare = root.querySelector("#compare");
  root.querySelector("#pin").addEventListener("click", () => {
    pinned = last;
    drawCompare();
    compare.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "nearest" });
  });
  root.querySelector("#unpin").addEventListener("click", () => {
    pinned = null;
    drawCompare();
  });
  function drawCompare() {
    compare.hidden = !pinned;
    root.querySelector("#pin").textContent = t(pinned ? "Pin this one as A" : "Pin as A to compare");
    if (!pinned) return;
    const [a, b] = [pinned, last];
    root.querySelector("#versus").innerHTML = `<span class="badge a">A</span> ${esc(a.name)}, ${esc(shockTerms(a.spec))}<br>
      <span class="badge b">B</span> ${esc(b.name)}, ${esc(shockTerms(b.spec))}`;
    const delta = b.result.gapUsd - a.result.gapUsd;
    root.querySelector("#deltas").innerHTML = [
      figure(t("Gap under A"), a.result.gapUsd),
      figure(t("Gap under B"), b.result.gapUsd, "", "alert"),
      figure(t("B against A"), Math.abs(delta), t(delta > 0 ? "more left unfilled" : delta < 0 ? "less left unfilled" : "the same gap")),
      `<div class="kpi"><span class="label">${t("Delay, A then B")}</span><strong>${esc(days(a.result.delayDays))} → ${esc(days(b.result.delayDays))}</strong></div>`,
    ].join("");
    rollUp(root.querySelector("#deltas"));
    const option = {
      grid: { left: 110, right: 70, top: 40, bottom: 30 },
      legend: {},
      tooltip: { trigger: "axis", valueFormatter: usd },
      xAxis: { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
      yAxis: { type: "category", inverse: true, data: MEASURES.map(([, label]) => t(label)), axisLabel: { color: css("--ink") } },
      series: [[a, "A", css("--accent-2")], [b, "B", css("--warn")]].map(([run, name, color]) => ({
        name, type: "bar", barMaxWidth: 16, itemStyle: { color, borderRadius: 2 },
        data: MEASURES.map(([key]) => run.result[key]),
        label: { show: true, position: "right", color: css("--muted"), formatter: (p) => usd(p.value) },
      })),
    };
    pair ??= chart(root.querySelector("#pair"), option);
    pair.setOption(option, { replaceMerge: ["series"] });
  }

  syncForm();
  drawChips();
  await go();
}

// A rising figure draws the eye to what changed. Reduced motion shows it at once.
function rollUp(node) {
  if (calm) return;
  for (const el of node.querySelectorAll("[data-usd]")) {
    const end = Number(el.dataset.usd);
    const start = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - start) / 900);
      el.textContent = usd(end * (1 - (1 - k) ** 3));
      if (k < 1 && el.isConnected) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
}

const figure = (label, value, note = "", tone = "") => `<div class="kpi ${tone}"><span class="label">${esc(label)}</span>
  <strong data-usd="${Number(value) || 0}">${esc(usd(value))}</strong>${note && `<span class="note">${esc(note)}</span>`}</div>`;

function story(spec, r, reporter) {
  const who = esc(reporter.countryName);
  if (!r.affectedUsd) return esc(t("Nothing {reporter} imported in {year} meets this shock.", { reporter: reporter.countryName, year: spec.year }));
  const lead = spec.productCode
    ? t("{value} of the imports of {reporter} under HS {code} would be hit over {weeks} weeks, {share} of all it buys in that time.", {
      value: hot(usd(r.affectedUsd)), reporter: who, code: esc(spec.productCode), weeks: spec.weeks, share: hot(pct(r.exposureShare)),
    })
    : t("{value} of the imports of {reporter} would be hit over {weeks} weeks, {share} of all it buys in that time.", {
      value: hot(usd(r.affectedUsd)), reporter: who, weeks: spec.weeks, share: hot(pct(r.exposureShare)),
    });
  const parts = [lead];
  if (r.reroutedUsd > 0) parts.push(t("{value} would still arrive by a longer lane, {days} late on average.", { value: hot(usd(r.reroutedUsd)), days: hot(days(r.delayDays)) }));
  const cut = r.routes.filter((x) => x.state === "cutOff" && x.affectedUsd > 0).map((x) => esc(t(x.name)));
  if (cut.length) parts.push(t("No sea lane is left from {regions}.", { regions: listed(cut) }));
  parts.push(r.strandedUsd > 0
    ? t("{stranded} would be stranded. The exporters the shock spares could make up {replaced}, which leaves a gap of {gap}.", {
      stranded: hot(usd(r.strandedUsd)), replaced: hot(usd(r.replacedUsd)), gap: `<b class="gap">${esc(usd(r.gapUsd))}</b>`,
    })
    : t("Nothing is stranded, since every ship hit has another lane."));
  const worst = r.products[0];
  if (worst?.gapUsd > 0) parts.push(t("The largest gap is in {product}, at {value}.", { product: `<b>${esc(worst.productCode)}</b> ${esc(worst.description)}`, value: hot(usd(worst.gapUsd)) }));
  return parts.join(" ");
}

function crisisOption(r, reporter) {
  const most = Math.max(...r.suppliers.map((s) => s.affectedUsd), 1);
  const widest = Math.max(...r.routes.map((x) => x.affectedUsd), 1);
  const width = (x) => 1.5 + 7 * Math.sqrt(x.affectedUsd / widest);
  const lane = (x, coords, lineStyle) => ({ name: t(x.name), coords, item: x, lineStyle });
  return {
    geo: {
      map: "world",
      silent: true,
      left: 0, right: 0, top: 0, bottom: 0,
      itemStyle: { areaColor: css("--land"), borderColor: css("--border"), borderWidth: 0.6 },
      regions: [
        ...r.suppliers.map((s) => ({
          name: shapeId(s.countryCode),
          itemStyle: { areaColor: s.cause === "rerouted" ? css("--supply") : css("--warn"), opacity: 0.3 + 0.7 * Math.sqrt(s.affectedUsd / most) },
        })),
        { name: shapeId(reporter.countryCode), itemStyle: { areaColor: css("--ink") } },
      ],
    },
    series: [
      {
        id: "calm", type: "lines", coordinateSystem: "geo", polyline: true, silent: true,
        data: r.routes.filter((x) => x.path && !x.state).map((x) => lane(x, x.path, { width: 1, color: css("--border"), opacity: 0.7 })),
      },
      {
        id: "broken", type: "lines", coordinateSystem: "geo", polyline: true,
        data: r.routes.filter((x) => x.path && x.state).map((x) => lane(x, x.path, {
          width: x.state === "rerouted" ? 1.5 : width(x), color: css("--warn"),
          type: x.state === "rerouted" ? "dotted" : "solid", opacity: x.state === "rerouted" ? 0.6 : 0.9,
        })),
      },
      {
        id: "detours", type: "lines", coordinateSystem: "geo", polyline: true, z: 3,
        effect: { show: !calm, constantSpeed: 45, symbol: "arrow", symbolSize: 7, trailLength: 0.15, color: css("--sold") },
        data: r.routes.filter((x) => x.detour).map((x) => lane(x, x.detour.path, { width: width(x), color: css("--sold"), type: "dashed", opacity: 0.9 })),
      },
      {
        id: "closed", type: "effectScatter", coordinateSystem: "geo", z: 4,
        rippleEffect: { scale: 5, brushType: "stroke", period: 2.5 },
        showEffectOn: calm ? "emphasis" : "render",
        symbolSize: 13,
        itemStyle: { color: css("--warn") },
        label: { show: true, position: "right", fontWeight: 600, color: css("--warn"), backgroundColor: "#ffffffeb", padding: [3, 5], borderRadius: 3, formatter: (p) => p.name },
        data: r.closed.map((c) => ({ name: t(c.name), value: c.at })),
      },
    ],
  };
}

const laneTip = (x) => [
  `<strong>${esc(t(x.name))}</strong>`,
  x.state && esc(t(CAUSE[x.state])),
  x.affectedUsd > 0 && t("{value} hit", { value: usd(x.affectedUsd) }),
  x.detour && esc(t("{km} longer, {days} late", { km: km(x.detour.extraKm), days: days(x.detour.extraDays) })),
].filter(Boolean).join("<br>");

function waterfallOption(r) {
  const steps = [
    [t("Hit"), r.affectedUsd, 0, css("--warn")],
    [t("Arrives late"), r.reroutedUsd, r.affectedUsd - r.reroutedUsd, css("--supply")],
    [t("Replaced"), r.replacedUsd, r.gapUsd, css("--sold")],
    [t("Gap"), r.gapUsd, 0, css("--ink")],
  ];
  return {
    grid: { left: 70, right: 20, top: 40, bottom: 30 },
    tooltip: { trigger: "axis", formatter: ([p]) => `<b>${esc(steps[p.dataIndex][0])}</b><br>${usd(steps[p.dataIndex][1])}` },
    xAxis: { ...axis(), type: "category", data: steps.map(([name]) => name), axisLabel: { color: css("--ink") } },
    yAxis: { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
    animationDuration: 900,
    animationEasing: "cubicOut",
    series: [
      { id: "base", type: "bar", stack: "fall", silent: true, emphasis: { disabled: true }, itemStyle: { color: "transparent" }, data: steps.map((s) => s[2]) },
      {
        id: "step", type: "bar", stack: "fall", barMaxWidth: 72,
        data: steps.map(([, value, , color]) => ({ value, itemStyle: { color, borderRadius: 3 } })),
        label: { show: true, position: "top", color: css("--ink"), fontWeight: 600, formatter: (p) => usd(p.value) },
      },
    ],
  };
}

function yearsOption(spec, r, at = String(spec.year)) {
  const area = (name, key, color, opacity) => ({
    id: key, name, type: "line", smooth: true, showSymbol: false, data: r.timeline.map((y) => y[key]),
    itemStyle: { color }, lineStyle: { color, width: 2 }, areaStyle: { color, opacity },
  });
  return {
    grid: { left: 70, right: 20, top: 40, bottom: 30 },
    legend: {},
    tooltip: { trigger: "axis", valueFormatter: usd },
    xAxis: { ...axis(), type: "category", boundaryGap: false, data: r.timeline.map((y) => String(y.year)) },
    yAxis: { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
    animationDuration: 1400,
    series: [
      { ...area(t("Imports in the same weeks"), "totalUsd", css("--border"), 0.15), smooth: false },
      {
        ...area(t("Hit"), "affectedUsd", css("--supply"), 0.3),
        markLine: { symbol: "none", silent: true, animation: false, lineStyle: { color: css("--ink"), type: "dashed" }, label: { formatter: at, color: css("--ink") }, data: [{ xAxis: at }] },
      },
      area(t("Stranded"), "strandedUsd", css("--warn"), 0.45),
    ],
  };
}

// One view draws a result for the scenario page and for a saved report.
export function resultView(node, reporter) {
  let parts;
  return function show(spec, r, name) {
    if (!parts) {
      node.append(html(`
        <div class="verdict">
          <p class="terms" id="terms"></p>
          <h2 id="name"></h2>
          <p class="story" id="story"></p>
        </div>
        <div class="kpis" id="figures"></div>
        <div class="panel"><h2>${t("Crisis map")}</h2>
          <p>${t("Closed straits pulse in red. Red lanes are cut and dotted ones are given up, while the green arrows are ships sent round the long way. Supplier countries are shaded by the value hit, in orange where it still arrives late, and {reporter} is dark.", { reporter: esc(reporter.countryName) })}</p>
          <div class="chart map" id="crisis"></div></div>
        <div class="grid">
          <div class="panel"><h2>${t("From the value hit to the gap")}</h2>
            <p>${t("What the shock hits, less what arrives late by another lane and less what the spared exporters replace, leaves the gap.")}</p>
            <div class="chart" id="waterfall"></div></div>
          <div class="panel"><h2>${t("The same shock in every year")}</h2>
            <p>${t("The shock run on the trade of each year, for the same weeks. The dashed line marks the year chosen.")}</p>
            <div class="controls replay"><button type="button" id="replay">${t("Replay the years")}</button><span class="muted" id="replay-note"></span></div>
            <div class="chart" id="years"></div></div>
        </div>
        <div class="panel after-grid"><h2>${t("Products with the largest gap")}</h2>
          <p>${t("Each product hit, with what arrives late, what spared exporters replace and the gap left. The last column names the largest spared exporters {reporter} could turn to. Click a product to investigate it.", { reporter: esc(reporter.countryName) })}</p>
          <div id="products"></div></div>
        <div class="panel"><h2>${t("Suppliers hit")}</h2><div id="suppliers"></div></div>`));
      parts = { waterfall: chart(node.querySelector("#waterfall"), waterfallOption(r)), years: chart(node.querySelector("#years"), yearsOption(spec, r)) };
      const crisis = node.querySelector("#crisis");
      loadWorld()
        .then(() => {
          if (!crisis.isConnected) return;
          parts.map = zoomable(chart(crisis, { tooltip: { formatter: (p) => (p.data?.item ? laneTip(p.data.item) : esc(p.name)) }, ...crisisOption(parts.r, reporter) }), "geo");
        })
        .catch(() => crisis.closest(".panel").remove());
      parts.products = table(node.querySelector("#products"), {
        data: r.products,
        paginationSize: 12,
        columns: [
          { title: t("Code"), field: "productCode", width: 90 },
          { title: t("Product"), field: "description", minWidth: 200, tooltip: true },
          usdColumn(t("Hit"), "affectedUsd", { width: 105 }),
          usdColumn(t("Arrives late"), "reroutedUsd", { width: 120 }),
          usdColumn(t("Replaced"), "replacedUsd", { width: 110 }),
          {
            title: t("Gap"), field: "gapUsd", hozAlign: "right", sorter: "number", width: 140,
            formatter: (c) => {
              const most = Math.max(...c.getTable().getData().map((p) => p.gapUsd), 1);
              return `<span class="gap-bar" style="--w:${(100 * c.getValue()) / most}%"></span>${esc(usd(c.getValue()))}`;
            },
          },
          pctColumn(t("Exposure share"), "exposureShare", { width: 130 }),
          { title: t("Could turn to"), field: "alternatives", headerSort: false, width: 140, formatter: (c) => esc(c.getValue().join(", ")) },
        ],
      });
      parts.products.on("rowClick", (_, row) => (location.hash = `#/product/${row.getData().productCode}?year=${parts.spec.year}`));
      parts.suppliers = table(node.querySelector("#suppliers"), {
        data: r.suppliers,
        paginationSize: 10,
        columns: [
          { title: t("Country"), field: "countryName", minWidth: 160 },
          { title: t("Why"), field: "cause", width: 130, formatter: (c) => `<span class="cause ${c.getValue()}">${esc(t(CAUSE[c.getValue()]))}</span>` },
          usdColumn(t("Imports in the period"), "valueUsd", { width: 170 }),
          usdColumn(t("Hit"), "affectedUsd", { width: 120 }),
        ],
      });
      parts.suppliers.on("rowClick", (_, row) => (location.hash = `#/country/${row.getData().countryCode}?year=${parts.spec.year}`));
      node.querySelector("#replay").addEventListener("click", () => replay(parts));
    } else {
      parts.waterfall.setOption(waterfallOption(r), { replaceMerge: ["series"] });
      parts.years.setOption(yearsOption(spec, r), { replaceMerge: ["series"] });
      parts.products.setData(r.products);
      parts.suppliers.setData(r.suppliers);
    }
    Object.assign(parts, { spec, r });
    clearInterval(parts.timer);
    node.querySelector("#replay-note").textContent = "";
    parts.map?.setOption(crisisOption(r, reporter), { replaceMerge: ["series"] });
    node.querySelector("#terms").textContent = shockTerms(spec);
    node.querySelector("#name").textContent = name;
    node.querySelector("#story").innerHTML = story(spec, r, reporter);
    node.querySelector("#figures").innerHTML = [
      figure(t("Hit"), r.affectedUsd, t("{share} of imports in the period", { share: pct(r.exposureShare) }), "alert"),
      figure(t("Arrives late"), r.reroutedUsd, t("by a longer lane"), "late"),
      figure(t("Stranded"), r.strandedUsd),
      figure(t("Replaced"), r.replacedUsd, t("by spared exporters"), "good"),
      figure(t("Gap"), r.gapUsd, t("{share} of imports in the period", { share: pct(r.gapShare, 2) }), "alert"),
      `<div class="kpi"><span class="label">${t("Delay")}</span><strong>${esc(days(r.delayDays))}</strong><span class="note">${t("value-weighted, at 14 knots")}</span></div>`,
    ].join("");
    rollUp(node.querySelector("#figures"));
  };
}

function replay(parts) {
  clearInterval(parts.timer);
  const { spec, r } = parts;
  const note = parts.years.getDom().closest(".panel").querySelector("#replay-note");
  let i = 0;
  const step = () => {
    if (i >= r.timeline.length || !note.isConnected) {
      clearInterval(parts.timer);
      parts.years.setOption(yearsOption(spec, r), { replaceMerge: ["series"] });
      return;
    }
    const y = r.timeline[i];
    parts.years.setOption(yearsOption(spec, r, String(y.year)), { replaceMerge: ["series"] });
    parts.years.dispatchAction({ type: "showTip", seriesIndex: 1, dataIndex: i });
    note.textContent = t("{year}: {hit} hit, {stranded} stranded", { year: y.year, hit: usd(y.affectedUsd), stranded: usd(y.strandedUsd) });
    i += 1;
  };
  step();
  parts.timer = setInterval(step, calm ? 1500 : 700);
}
