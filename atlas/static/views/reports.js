import { api, esc, html, pct, table } from "../lib.js";
import { showResult } from "./scenario.js";

const stamp = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });

export default async function reports(root, [id]) {
  return id ? report(root, id) : list(root);
}

async function list(root) {
  const rows = await api("/reports");
  root.append(html(`
    <div class="head">
      <h1>Evidence reports</h1>
      <p class="lede">Each report freezes a scenario, its result and the exact BACI archive it came from. Reports are
        never recalculated, so a newer release leaves them as they were saved.</p>
    </div>
    <div class="panel"><div id="reports"></div></div>`));
  const grid = table(root.querySelector("#reports"), {
    data: rows,
    placeholder: "No reports yet. Save one from the scenario explorer.",
    columns: [
      { title: "Title", field: "title", minWidth: 240 },
      { title: "Mode", field: "spec.mode", width: 100 },
      { title: "Product", field: "spec.productCode", width: 100 },
      { title: "Year", field: "spec.year", width: 80 },
      { title: "Reduction", field: "spec.reduction", hozAlign: "right", sorter: "number", formatter: (c) => pct(Number(c.getValue()), 0), width: 110 },
      { title: "Saved", field: "createdAt", formatter: (c) => stamp.format(new Date(c.getValue())), width: 180 },
    ],
  });
  grid.on("rowClick", (_, row) => (location.hash = `#/reports/${row.getData()._id}`));
}

async function report(root, id) {
  const r = await api(`/reports/${id}`);
  const { spec, snapshot } = r;
  root.append(html(`
    <div class="head">
      <h1>${esc(r.title)}</h1>
      <p class="lede">Saved ${esc(stamp.format(new Date(r.createdAt)))}. ${spec.mode === "product"
        ? `Product ${esc(spec.productCode)}`
        : "All products"}, ${spec.year}, a ${pct(Number(spec.reduction), 0)} cut from ${spec.suppliers.length} supplier${spec.suppliers.length === 1 ? "" : "s"}.</p>
      <div class="controls"><a href="/api/reports/${esc(id)}.csv" download><button class="primary">Download CSV</button></a></div>
    </div>
    <div class="grid">
      <div class="panel"><h2>Result</h2><div id="result"></div></div>
      <div class="panel"><h2>Provenance</h2>
        <dl class="facts">
          <dt>Source</dt><dd>${esc(snapshot.source.name)} ${esc(snapshot.source.classification)}, release ${esc(snapshot.source.release)}</dd>
          <dt>Snapshot</dt><dd><code>${esc(snapshot.id)}</code></dd>
          <dt>Archive</dt><dd><code>${esc(snapshot.archive.filename)}</code></dd>
          <dt>SHA-256</dt><dd><code>${esc(snapshot.archive.sha256)}</code></dd>
          <dt>Retrieved</dt><dd>${esc(stamp.format(new Date(snapshot.archive.retrievedAt)))}</dd>
          <dt>Calculation</dt><dd>version ${esc(r.calculationVersion)}</dd>
          <dt>Citation</dt><dd>${esc(snapshot.source.citation)}</dd>
        </dl>
        <h2 style="margin-top:1rem">Limitations</h2>
        <ul>${r.limitations.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>
      </div>
    </div>
    <div id="details"></div>`));
  showResult(root, spec, r.result);
}
