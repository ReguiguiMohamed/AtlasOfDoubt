import { lang, t } from "../i18n.js";
import { api, axis, chart, count, css, esc, html, index, indexColumn, kpi, pct, pctColumn, query, scoped, state, table, usd, usdColumn } from "../lib.js";

const LABEL = t("Historical import value exposed under this scenario");
const BARS = 15;

export default async function scenario(root, _, params) {
  const mode = params.get("mode") === "country" ? "country" : "product";
  const years = [...state.snapshot.years].reverse();
  const year = Number(params.get("year")) || years[0];
  const reduction = Math.min(100, Math.max(0, Number(params.get("reduction") ?? 50)));
  const chosen = new Set((params.get("suppliers") ?? "").split(",").filter(Boolean).map(Number));
  const code = params.get("code") ?? "";

  root.append(html(`
    <div class="head">
      <h1>${t("Disruption scenario")}</h1>
      <p class="lede">${t("Cut the imports from chosen suppliers by a percentage and see how much of the historical import value of {reporter} sits behind them. Other suppliers are left as they were, with no replacement and no price response.", { reporter: esc(state.reporter.countryName) })}</p>
      <div class="controls">
        <span class="segmented">
          <a href="#/scenario?mode=product" class="${mode === "product" ? "active" : ""}">${t("One product")}</a>
          <a href="#/scenario?mode=country" class="${mode === "country" ? "active" : ""}">${t("Supplier countries")}</a>
        </span>
      </div>
      <form class="controls">
        ${mode === "product" ? `<label>${t("HS code")} <input name="code" value="${esc(code)}" pattern="(\\d{2}){1,3}" placeholder="100119" size="8"></label>` : ""}
        <label>${t("Year")} <select name="year">${years.map((y) => `<option ${y === year ? "selected" : ""}>${y}</option>`).join("")}</select></label>
        <label>${t("Reduction")} <span><input name="reduction" type="range" min="0" max="100" step="5" value="${reduction}"> <output>${pct(reduction / 100, 0)}</output></span></label>
      </form>
    </div>
    <div class="grid">
      <div class="panel"><h2>${t(mode === "product" ? "Suppliers of this product" : "Supplier countries")}</h2>
        ${mode === "country" ? `<input type="search" id="filter" placeholder="${t("Filter countries")}" style="width:100%;margin-bottom:.5rem">` : ""}
        <div class="checklist" id="choices"><p class="note">${mode === "product" ? t("Enter an HS code to list its suppliers.") : ""}</p></div>
      </div>
      <div class="panel"><h2>${t("Result")}</h2><div id="result"><p class="note">${t("Pick at least one supplier.")}</p></div></div>
    </div>
    <div id="details"></div>
  `));

  const form = root.querySelector("form");
  const choices = root.querySelector("#choices");
  const output = root.querySelector("output");

  const spec = () => ({
    snapshot: state.snapshot._id,
    reporter: state.reporter.countryCode,
    year: Number(form.year.value),
    mode,
    productCode: mode === "product" ? form.code.value.trim() : null,
    suppliers: [...choices.querySelectorAll("input:checked")].map((i) => Number(i.value)),
    reduction: String(Number(form.reduction.value) / 100),
  });

  const remember = (s) => {
    const shown = { mode, code: s.productCode, year: s.year, reduction: form.reduction.value, suppliers: s.suppliers.join(",") };
    history.replaceState(null, "", `#/scenario?${query(shown)}`);
  };

  async function listChoices() {
    if (mode === "country") {
      const countries = state.detail.countries
        .filter((c) => c.countryCode !== state.reporter.countryCode)
        .sort((a, b) => a.countryName.localeCompare(b.countryName, lang));
      choices.innerHTML = countries.map((c) => `<label data-name="${esc(c.countryName.toLowerCase())}">
        <input type="checkbox" value="${c.countryCode}" ${chosen.has(c.countryCode) ? "checked" : ""}> ${esc(c.countryName)}</label>`).join("");
      return;
    }
    const value = form.code.value.trim();
    if (!/^(\d{2}){1,3}$/.test(value)) return;
    const history = await api(`/products/${value}/history?${scoped()}`);
    const suppliers = history.years.find((y) => y.year === Number(form.year.value))?.suppliers ?? [];
    choices.innerHTML = suppliers.length
      ? suppliers.map((s) => `<label><input type="checkbox" value="${s.countryCode}" ${chosen.has(s.countryCode) ? "checked" : ""}>
          ${esc(s.countryName)}<span class="value">${usd(s.valueUsd)} · ${pct(s.share)}</span></label>`).join("")
      : `<p class="notice">${esc(t("No recorded imports of {code} into {reporter} in {year}.", { reporter: state.reporter.countryName, code: value, year: form.year.value }))}</p>`;
  }

  let timer;
  let latest = 0;
  async function update() {
    const s = spec();
    output.textContent = pct(form.reduction.value / 100, 0);
    chosen.clear();
    s.suppliers.forEach((c) => chosen.add(c));
    remember(s);
    if (!s.suppliers.length) {
      root.querySelector("#result").innerHTML = `<p class="note">${t("Pick at least one supplier.")}</p>`;
      root.querySelector("#details").replaceChildren();
      return;
    }
    const ticket = ++latest;
    const { result } = await api("/scenarios/preview", { method: "POST", body: JSON.stringify(s) });
    if (ticket !== latest) return;
    showResult(root, s, result);
    offerSave(root.querySelector("#result"), s);
  }
  const later = () => {
    clearTimeout(timer);
    timer = setTimeout(() => update().catch(fail), 150);
  };
  const fail = (error) => (root.querySelector("#result").innerHTML = `<p class="error">${esc(error.message)}</p>`);

  form.addEventListener("input", (e) => {
    if (e.target.name === "reduction") return later();
  });
  form.addEventListener("change", async (e) => {
    if (e.target.name === "reduction") return;
    if (mode === "product") await listChoices().catch(fail);
    later();
  });
  form.addEventListener("submit", (e) => e.preventDefault());
  choices.addEventListener("change", later);
  root.querySelector("#filter")?.addEventListener("input", (e) => {
    const term = e.target.value.trim().toLowerCase();
    choices.querySelectorAll("label").forEach((l) => (l.hidden = !l.dataset.name.includes(term)));
  });

  await listChoices();
  await update();
}

function offerSave(node, s) {
  node.append(html(`<form class="controls"><label>${t("Report title")} <input name="title" required maxlength="200" size="40"
    placeholder="${t("What this scenario asks")}"></label><button class="primary">${t("Save evidence report")}</button></form>`));
  const form = node.querySelector("form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    form.querySelector("button").disabled = true;
    try {
      const { id } = await api("/reports", { method: "POST", body: JSON.stringify({ ...s, title: form.title.value.trim() }) });
      location.hash = `#/reports/${id}`;
    } catch (error) {
      form.querySelector("button").disabled = false;
      form.insertAdjacentHTML("beforeend", `<p class="error">${esc(error.message)}</p>`);
    }
  });
}

export function showResult(root, s, r) {
  (s.mode === "product" ? showProduct : showCountry)(root, s, r);
}

function showProduct(root, s, r) {
  root.querySelector("#result").innerHTML = `
    <p><b>${esc(s.productCode)}</b> ${esc(r.description)}, ${s.year}</p>
    <div class="kpis">
      ${kpi(LABEL, usd(r.affectedUsd))}
      ${kpi(t("Share of this product's imports"), pct(r.exposureShare))}
      ${kpi(t("Remaining imports"), usd(r.remainingUsd), t("of {value}", { value: usd(r.baseline.totalUsd) }))}
      ${kpi(t("HHI before and after"), `${index(r.baseline.hhi)} → ${index(r.remaining.hhi)}`)}
    </div>`;
  root.querySelector("#result .kpi").classList.add("alert");

  const shown = r.suppliers.slice(0, BARS);
  root.querySelector("#details").replaceChildren(html(`
    <div class="panel" style="margin-top:1.25rem"><h2>${t("Before and after, by supplier")}</h2><div class="chart tall" id="compare"></div></div>
    <div class="panel"><div id="rows"></div></div>`));
  chart(root.querySelector("#compare"), {
    grid: { left: 140, right: 30, top: 40, bottom: 30 },
    legend: { textStyle: { color: css("--muted") } },
    tooltip: { trigger: "axis", valueFormatter: usd },
    xAxis: { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
    yAxis: { type: "category", inverse: true, data: shown.map((x) => x.countryName), axisLabel: { color: css("--ink") } },
    series: [
      { name: t("Baseline"), type: "bar", barMaxWidth: 18, data: shown.map((x) => x.baselineUsd), itemStyle: { color: css("--accent-2") } },
      { name: t("After the cut"), type: "bar", barMaxWidth: 18, data: shown.map((x) => ({ value: x.remainingUsd, itemStyle: { color: x.selected ? css("--warn") : css("--accent") } })) },
    ],
  });
  table(root.querySelector("#rows"), {
    data: r.suppliers,
    columns: [
      { title: t("Country"), field: "countryName", minWidth: 150 },
      { title: t("Cut"), field: "selected", formatter: "tickCross", width: 70, hozAlign: "center" },
      usdColumn(t("Baseline"), "baselineUsd"),
      pctColumn(t("Share"), "baselineShare"),
      usdColumn(t("After"), "remainingUsd"),
      pctColumn(t("Share after"), "remainingShare"),
    ],
  });
}

function showCountry(root, s, r) {
  root.querySelector("#result").innerHTML = `
    <div class="kpis">
      ${kpi(LABEL, usd(r.affectedUsd), String(s.year))}
      ${kpi(t("Share of all imports"), pct(r.exposureShare, 2), t("of {value}", { value: usd(r.totalImportsUsd) }))}
      ${kpi(t("Products touched"), count(r.products.length))}
    </div>
    <p class="note">${r.suppliers.map((x) => esc(t("{name} supplied {value}", { name: x.countryName, value: usd(x.valueUsd) }))).join(", ")}.</p>`;
  root.querySelector("#result .kpi").classList.add("alert");

  const top = r.products.slice(0, BARS);
  root.querySelector("#details").replaceChildren(html(`
    <div class="panel" style="margin-top:1.25rem"><h2>${t("Products with the most value exposed")}</h2><div class="chart tall" id="top"></div></div>
    <div class="panel"><h2>${t("Every product touched")}</h2><p>${t("Sort by exposure share to find products where the chosen suppliers are most of the supply, whatever the size.")}</p><div id="rows"></div></div>`));
  chart(root.querySelector("#top"), {
    grid: { left: 80, right: 70, top: 10, bottom: 30 },
    tooltip: { formatter: (p) => `<b>${esc(top[p.dataIndex].productCode)}</b> ${esc(top[p.dataIndex].description)}<br>
      ${t("{value} exposed, {share} of the product's imports", { value: usd(p.value), share: pct(top[p.dataIndex].exposureShare) })}` },
    xAxis: { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
    yAxis: { type: "category", inverse: true, data: top.map((p) => p.productCode), axisLabel: { color: css("--ink"), fontFamily: css("--mono") } },
    series: [{
      type: "bar",
      barMaxWidth: 28,
      data: top.map((p) => p.affectedUsd),
      itemStyle: { color: css("--warn") },
      label: { show: true, position: "right", color: css("--muted"), formatter: (p) => pct(top[p.dataIndex].exposureShare, 0) },
    }],
  });
  const rows = table(root.querySelector("#rows"), {
    data: r.products,
    columns: [
      { title: t("Code"), field: "productCode", width: 90 },
      { title: t("Product"), field: "description", minWidth: 220, tooltip: true },
      usdColumn(t("Imports"), "totalUsd", { width: 120 }),
      usdColumn(t("Exposed"), "affectedUsd", { width: 110 }),
      pctColumn(t("Exposure share"), "exposureShare", { width: 140 }),
      indexColumn(t("HHI before"), "baselineHhi", { width: 110 }),
      indexColumn(t("HHI after"), "remainingHhi", { width: 110 }),
    ],
  });
  rows.on("rowClick", (_, row) => (location.hash = `#/product/${row.getData().productCode}?year=${s.year}`));
}
