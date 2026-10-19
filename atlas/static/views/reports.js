import { lang, t } from "../i18n.js";
import { api, esc, html, pct, query, state, table, usd } from "../lib.js";
import { resultView, scenarioLink, shockName, shockTerms } from "./scenario.js";

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
    placeholder: t("No reports yet. Save one from the disruption scenario."),
    columns: [
      { title: t("Title"), field: "title", minWidth: 220 },
      { title: t("Year"), field: "spec.year", width: 80 },
      { title: "HS", field: "spec.productCode", width: 90 },
      { title: t("Severity"), field: "spec.reduction", hozAlign: "right", sorter: "number", formatter: (c) => pct(Number(c.getValue()), 0), width: 100 },
      { title: t("Weeks"), field: "spec.weeks", hozAlign: "right", width: 85 },
      { title: t("Hit"), field: "result.affectedUsd", hozAlign: "right", sorter: "number", formatter: (c) => usd(c.getValue()), width: 100 },
      { title: t("Gap"), field: "result.gapUsd", hozAlign: "right", sorter: "number", formatter: (c) => usd(c.getValue()), width: 100 },
      { title: t("Delay"), field: "result.delayDays", hozAlign: "right", sorter: "number", formatter: (c) => (c.getValue() == null ? "" : t("{days} days", { days: c.getValue().toFixed(1) })), width: 100 },
      { title: t("Saved"), field: "createdAt", formatter: (c) => stamp.format(new Date(c.getValue())), width: 170 },
    ],
  });
  grid.on("rowClick", (_, row) => (location.hash = `#/reports/${row.getData()._id}`));
}

async function report(root, id) {
  const [r, presets] = await Promise.all([api(`/reports/${id}`), api(`/scenarios/presets?${query({ snapshot: state.snapshot._id })}`)]);
  const { spec, snapshot } = r;
  root.append(html(`
    <div class="head">
      <a class="back-link" href="#/reports">← ${t("All reports")}</a>
      <h1>${esc(r.title)}</h1>
      <p class="lede">${esc(t("Saved {date} for {reporter}.", { date: stamp.format(new Date(r.createdAt)), reporter: r.reporter.countryName }))} ${esc(shockTerms(spec))}.</p>
      <div class="controls">
        <a href="/api/reports/${esc(id)}.csv" download><button class="primary">${t("Download CSV")}</button></a>
        <button type="button" id="print">${t("Print or save as PDF")}</button>
        <a href="${esc(scenarioLink(spec))}"><button type="button">${t("Open in the simulator")}</button></a>
        <button type="button" id="share">${t("Copy link")}</button>
      </div>
    </div>
    <div id="result"></div>
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
    </div>`));
  root.querySelector("#print").addEventListener("click", () => print());
  root.querySelector("#share").addEventListener("click", async (e) => {
    await navigator.clipboard?.writeText(location.href).catch(() => {});
    e.target.textContent = t("Link copied");
  });
  resultView(root.querySelector("#result"), r.reporter)(spec, r.result, shockName(spec, r.result, presets));
}
