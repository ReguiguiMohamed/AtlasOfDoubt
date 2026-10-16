import { api, axis, chart, css, esc, html, index, indexColumn, kpi, pct, pctColumn, query, snapshotDetail, state, table, usd, usdColumn } from "../lib.js";

const LABEL = "Historical import value exposed under this scenario";
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
      <h1>Disruption scenario</h1>
      <p class="lede">Cut the imports from chosen suppliers by a percentage and see how much of Tunisia's
        historical import value sits behind them. Other suppliers are left as they were, with no replacement
        and no price response.</p>
      <div class="controls">
        <span class="segmented">
          <a href="#/scenario?mode=product" class="${mode === "product" ? "active" : ""}">One product</a>
          <a href="#/scenario?mode=country" class="${mode === "country" ? "active" : ""}">Supplier countries</a>
        </span>
      </div>
      <form class="controls">
        ${mode === "product" ? `<label>HS code <input name="code" value="${esc(code)}" pattern="(\\d{2}){1,3}" placeholder="100119" size="8"></label>` : ""}
        <label>Year <select name="year">${years.map((y) => `<option ${y === year ? "selected" : ""}>${y}</option>`).join("")}</select></label>
        <label>Reduction <span><input name="reduction" type="range" min="0" max="100" step="5" value="${reduction}"> <output>${reduction}%</output></span></label>
      </form>
    </div>
    <div class="grid">
      <div class="panel"><h2>${mode === "product" ? "Suppliers of this product" : "Supplier countries"}</h2>
        ${mode === "country" ? `<input type="search" id="filter" placeholder="Filter countries" style="width:100%;margin-bottom:.5rem">` : ""}
        <div class="checklist" id="choices"><p class="note">${mode === "product" ? "Enter an HS code to list its suppliers." : ""}</p></div>
      </div>
      <div class="panel"><h2>Result</h2><div id="result"><p class="note">Pick at least one supplier.</p></div></div>
    </div>
    <div id="details"></div>
  `));

  const form = root.querySelector("form");
  const choices = root.querySelector("#choices");
  const output = root.querySelector("output");

  const spec = () => ({
    snapshot: state.snapshot._id,
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
      const detail = await snapshotDetail();
      const countries = detail.countries.filter((c) => c.countryCode !== detail.reporter.countryCode);
      choices.innerHTML = countries.map((c) => `<label data-name="${esc(c.countryName.toLowerCase())}">
        <input type="checkbox" value="${c.countryCode}" ${chosen.has(c.countryCode) ? "checked" : ""}> ${esc(c.countryName)}</label>`).join("");
      return;
    }
    const value = form.code.value.trim();
    if (!/^(\d{2}){1,3}$/.test(value)) return;
    const history = await api(`/products/${value}/history?${query({ snapshot: state.snapshot._id })}`);
    const suppliers = history.years.find((y) => y.year === Number(form.year.value))?.suppliers ?? [];
    choices.innerHTML = suppliers.length
      ? suppliers.map((s) => `<label><input type="checkbox" value="${s.countryCode}" ${chosen.has(s.countryCode) ? "checked" : ""}>
          ${esc(s.countryName)}<span class="value">${usd(s.valueUsd)} · ${pct(s.share)}</span></label>`).join("")
      : `<p class="notice">No recorded imports of ${esc(value)} into Tunisia in ${esc(form.year.value)}.</p>`;
  }

  let timer;
  let latest = 0;
  async function update() {
    const s = spec();
    output.textContent = `${form.reduction.value}%`;
    chosen.clear();
    s.suppliers.forEach((c) => chosen.add(c));
    remember(s);
    if (!s.suppliers.length) {
      root.querySelector("#result").innerHTML = `<p class="note">Pick at least one supplier.</p>`;
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
  node.append(html(`<form class="controls"><label>Report title <input name="title" required maxlength="200" size="40"
    placeholder="What this scenario asks"></label><button class="primary">Save evidence report</button></form>`));
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
      ${kpi("Share of this product's imports", pct(r.exposureShare))}
      ${kpi("Remaining imports", usd(r.remainingUsd), `of ${usd(r.baseline.totalUsd)}`)}
      ${kpi("HHI before and after", `${index(r.baseline.hhi)} → ${index(r.remaining.hhi)}`)}
    </div>`;
  root.querySelector("#result .kpi").classList.add("alert");

  const shown = r.suppliers.slice(0, BARS);
  root.querySelector("#details").replaceChildren(html(`
    <div class="panel" style="margin-top:1.25rem"><h2>Before and after, by supplier</h2><div class="chart tall" id="compare"></div></div>
    <div class="panel"><div id="rows"></div></div>`));
  chart(root.querySelector("#compare"), {
    grid: { left: 140, right: 30, top: 40, bottom: 30 },
    legend: { textStyle: { color: css("--muted") } },
    tooltip: { trigger: "axis", valueFormatter: usd },
    xAxis: { ...axis(), type: "value", axisLabel: { color: css("--muted"), formatter: usd } },
    yAxis: { type: "category", inverse: true, data: shown.map((x) => x.countryName), axisLabel: { color: css("--ink") } },
    series: [
      { name: "Baseline", type: "bar", barMaxWidth: 18, data: shown.map((x) => x.baselineUsd), itemStyle: { color: css("--accent-2") } },
      { name: "After the cut", type: "bar", barMaxWidth: 18, data: shown.map((x) => ({ value: x.remainingUsd, itemStyle: { color: x.selected ? css("--warn") : css("--accent") } })) },
    ],
  });
  table(root.querySelector("#rows"), {
    data: r.suppliers,
    columns: [
      { title: "Country", field: "countryName", minWidth: 150 },
      { title: "Cut", field: "selected", formatter: "tickCross", width: 70, hozAlign: "center" },
      usdColumn("Baseline", "baselineUsd"),
      pctColumn("Share", "baselineShare"),
      usdColumn("After", "remainingUsd"),
      pctColumn("Share after", "remainingShare"),
    ],
  });
}

function showCountry(root, s, r) {
  root.querySelector("#result").innerHTML = `
    <div class="kpis">
      ${kpi(LABEL, usd(r.affectedUsd), String(s.year))}
      ${kpi("Share of all Tunisian imports", pct(r.exposureShare, 2), `of ${usd(r.totalImportsUsd)}`)}
      ${kpi("Products touched", r.products.length.toLocaleString("en"))}
    </div>
    <p class="note">${r.suppliers.map((x) => `${esc(x.countryName)} supplied ${usd(x.valueUsd)}`).join(", ")}.</p>`;
  root.querySelector("#result .kpi").classList.add("alert");

  const top = r.products.slice(0, BARS);
  root.querySelector("#details").replaceChildren(html(`
    <div class="panel" style="margin-top:1.25rem"><h2>Products with the most value exposed</h2><div class="chart tall" id="top"></div></div>
    <div class="panel"><h2>Every product touched</h2><p>Sort by exposure share to find products where the chosen
      suppliers are most of the supply, whatever the size.</p><div id="rows"></div></div>`));
  chart(root.querySelector("#top"), {
    grid: { left: 80, right: 70, top: 10, bottom: 30 },
    tooltip: { formatter: (p) => `<b>${esc(top[p.dataIndex].productCode)}</b> ${esc(top[p.dataIndex].description)}<br>
      ${usd(p.value)} exposed, ${pct(top[p.dataIndex].exposureShare)} of the product's imports` },
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
      { title: "Code", field: "productCode", width: 90 },
      { title: "Product", field: "description", minWidth: 220, tooltip: true },
      usdColumn("Imports", "totalUsd", { width: 110 }),
      usdColumn("Exposed", "affectedUsd", { width: 110 }),
      pctColumn("Exposure share", "exposureShare", { width: 140 }),
      indexColumn("HHI before", "baselineHhi", { width: 110 }),
      indexColumn("HHI after", "remainingHhi", { width: 110 }),
    ],
  });
  rows.on("rowClick", (_, row) => (location.hash = `#/product/${row.getData().productCode}?year=${s.year}`));
}
