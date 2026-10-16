import { api, disposeCharts, esc, state } from "./lib.js";
import overview from "./views/overview.js";
import product from "./views/product.js";
import scenario from "./views/scenario.js";

const routes = { overview, product, scenario };
const main = document.getElementById("view");
const picker = document.getElementById("snapshot");

async function render() {
  const [path, search] = location.hash.replace(/^#\/?/, "").split("?");
  const [name, ...rest] = path.split("/");
  const view = routes[name] ?? overview;
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", routes[a.dataset.nav] === view));
  disposeCharts();
  // A slow view keeps writing into its own detached section, never into the next one.
  const section = document.createElement("section");
  main.replaceChildren(section);
  if (!state.snapshot) {
    section.innerHTML = `<div class="empty"><h1>No snapshot yet</h1><p>Import a BACI release first:</p>
      <pre>python -m atlas.ingest data/raw/BACI_HS12_V202601.zip</pre></div>`;
    return;
  }
  try {
    await view(section, rest, new URLSearchParams(search));
  } catch (error) {
    section.innerHTML = `<p class="error">${esc(error.message)}</p>`;
  }
}

function showCitation() {
  const source = state.snapshot?.source;
  document.getElementById("citation").innerHTML = source
    ? `Data: ${esc(source.name)} ${esc(source.classification)}, release ${esc(source.release)}, ${esc(source.valueUnit)}.
       ${esc(source.citation)} Licence: ${esc(source.license)}.`
    : "";
}

state.snapshots = await api("/snapshots");
let saved = null;
try {
  saved = localStorage.getItem("snapshot");
} catch {}
state.snapshot = state.snapshots.find((s) => s._id === saved) ?? state.snapshots[0] ?? null;
picker.innerHTML = state.snapshots.map((s) => `<option value="${esc(s._id)}">${esc(s._id)}</option>`).join("");
if (state.snapshot) picker.value = state.snapshot._id;
picker.addEventListener("change", () => {
  state.snapshot = state.snapshots.find((s) => s._id === picker.value);
  try {
    localStorage.setItem("snapshot", picker.value);
  } catch {}
  showCitation();
  render();
});
window.addEventListener("hashchange", render);
showCitation();
render();
