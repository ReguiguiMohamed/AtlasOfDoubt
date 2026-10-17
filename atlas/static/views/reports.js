import { lang, t } from "../i18n.js";
import { api, esc, html, pct, query, state, table } from "../lib.js";
import { showResult } from "./scenario.js";

const stamp = new Intl.DateTimeFormat(lang, { dateStyle: "medium", timeStyle: "short" });

export default async function reports(root, [id]) {
  return id ? report(root, id) : list(root);
}

async function list(root) {
  const rows = await api(`/reports?${query({ reporter: state.reporter.countryCode })}`);
  root.append(html(`
    <div class="head">
      <h1>${t("Evidence reports, {reporter}", { reporter: esc(state.reporter.countryName) })}</h1>
      <p class="lede">${t("Each report freezes a scenario, its result and the exact BACI archive it came from. Reports are never recalculated, so a newer release leaves them as they were saved.")}</p>
    </div>
    <div class="panel"><div id="reports"></div></div>`));
  const grid = table(root.querySelector("#reports"), {
    data: rows,
    placeholder: t("No reports yet. Save one from the scenario explorer."),
    columns: [
      { title: t("Title"), field: "title", minWidth: 240 },
      { title: t("Mode"), field: "spec.mode", formatter: (c) => t(c.getValue()), width: 100 },
      { title: t("Product"), field: "spec.productCode", width: 100 },
      { title: t("Year"), field: "spec.year", width: 80 },
      { title: t("Reduction"), field: "spec.reduction", hozAlign: "right", sorter: "number", formatter: (c) => pct(Number(c.getValue()), 0), width: 110 },
      { title: t("Saved"), field: "createdAt", formatter: (c) => stamp.format(new Date(c.getValue())), width: 180 },
    ],
  });
  grid.on("rowClick", (_, row) => (location.hash = `#/reports/${row.getData()._id}`));
}

async function report(root, id) {
  const r = await api(`/reports/${id}`);
  const { spec, snapshot } = r;
  const scope = spec.mode === "product" ? t("Product {code}", { code: spec.productCode }) : t("All products");
  const cut = pct(Number(spec.reduction), 0);
  const summary = spec.suppliers.length === 1
    ? t("{scope}, {year}, a {cut} cut from 1 supplier.", { scope, year: spec.year, cut })
    : t("{scope}, {year}, a {cut} cut from {count} suppliers.", { scope, year: spec.year, cut, count: spec.suppliers.length });
  root.append(html(`
    <div class="head">
      <h1>${esc(r.title)}</h1>
      <p class="lede">${esc(t("Saved {date}.", { date: stamp.format(new Date(r.createdAt)) }))} ${esc(summary)}</p>
      <div class="controls">
        <a href="/api/reports/${esc(id)}.csv" download><button class="primary">${t("Download CSV")}</button></a>
        <button type="button" id="print">${t("Print or save as PDF")}</button>
      </div>
    </div>
    <div class="grid">
      <div class="panel"><h2>${t("Result")}</h2><div id="result"></div></div>
      <div class="panel"><h2>${t("Provenance")}</h2>
        <dl class="facts">
          <dt>${t("Country")}</dt><dd>${esc(r.reporter.countryName)} <code>${esc(r.reporter.isoCode)}</code></dd>
          <dt>${t("Source")}</dt><dd>${esc(snapshot.source.name)} ${esc(snapshot.source.classification)}, ${esc(t("release {release}", { release: snapshot.source.release }))}</dd>
          <dt>${t("Snapshot")}</dt><dd><code>${esc(snapshot.id)}</code></dd>
          <dt>${t("Archive")}</dt><dd><code>${esc(snapshot.archive.filename)}</code></dd>
          <dt>SHA-256</dt><dd><code>${esc(snapshot.archive.sha256)}</code></dd>
          <dt>${t("Retrieved")}</dt><dd>${esc(stamp.format(new Date(snapshot.archive.retrievedAt)))}</dd>
          <dt>${t("Calculation")}</dt><dd>${esc(t("version {version}", { version: r.calculationVersion }))}</dd>
          <dt>${t("Citation")}</dt><dd>${esc(snapshot.source.citation)}</dd>
        </dl>
        <h2 style="margin-top:1rem">${t("Limitations")}</h2>
        <ul>${r.limitations.map((l) => `<li>${esc(t(l))}</li>`).join("")}</ul>
      </div>
    </div>
    <div id="details"></div>`));
  root.querySelector("#print").addEventListener("click", () => print());
  showResult(root, spec, r.result);
}
