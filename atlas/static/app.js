import { lang, switchLang, t } from "./i18n.js";
import { api, disposeCharts, esc, snapshotDetail, state } from "./lib.js";
import overview from "./views/overview.js";
import country from "./views/country.js";
import product from "./views/product.js";
import reports from "./views/reports.js";
import seaRoutes from "./views/routes.js";
import scenario from "./views/scenario.js";

const routes = { overview, product, country, routes: seaRoutes, scenario, reports };
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
    section.innerHTML = `<div class="empty"><h1>${t("No snapshot yet")}</h1><p>${t("Import a BACI release first:")}</p>
      <pre>python -m atlas.ingest data/raw/BACI_HS12_V202601.zip</pre></div>`;
    return;
  }
  try {
    await snapshotDetail();
    await view(section, rest, new URLSearchParams(search));
  } catch (error) {
    section.innerHTML = `<p class="error">${esc(error.message)}</p>`;
  }
}

function showCitation() {
  const source = state.snapshot?.source;
  document.getElementById("citation").innerHTML = source
    ? esc(t("Data: {name} {classification}, release {release}, {unit}. {citation} Licence: {license}.", {
        ...source,
        unit: t(source.valueUnit),
      }))
    : "";
}

document.querySelectorAll("[data-i18n]").forEach((node) => (node.textContent = t(node.textContent)));
document.querySelectorAll("[data-lang]").forEach((button) => {
  button.classList.toggle("active", button.dataset.lang === lang);
  button.addEventListener("click", () => button.dataset.lang !== lang && switchLang(button.dataset.lang));
});

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
