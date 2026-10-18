import { lang, switchLang, t } from "./i18n.js";
import { api, countryPicker, disposeCharts, esc, html, snapshotDetail, state } from "./lib.js";
import overview from "./views/overview.js";
import exports from "./views/exports.js";
import country from "./views/country.js";
import product from "./views/product.js";
import reports from "./views/reports.js";
import seaRoutes from "./views/routes.js";
import scenario from "./views/scenario.js";

const routes = { overview, exports, product, country, routes: seaRoutes, scenario, reports };
const main = document.getElementById("view");
const picker = document.getElementById("snapshot");
const reporterPicker = document.getElementById("reporter");
const navigation = document.getElementById("navigation");
const menu = document.getElementById("nav-toggle");

function setMenu(open) {
  menu.setAttribute("aria-expanded", String(open));
  document.getElementById("menu-label").textContent = t(open ? "Close" : "Menu");
  document.getElementById("menu-icon").textContent = open ? "×" : "☰";
  navigation.classList.toggle("open", open);
}

menu.addEventListener("click", () => setMenu(menu.getAttribute("aria-expanded") !== "true"));
navigation.addEventListener("click", (event) => {
  if (event.target.closest("a")) setMenu(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && menu.getAttribute("aria-expanded") === "true") {
    setMenu(false);
    menu.focus();
  }
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".top")) setMenu(false);
});

function remembered(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function remember(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {}
}

// The reporter sits in the query string beside the language, so a shared link opens on the same country.
function chooseReporter(code) {
  state.reporter = state.detail.countries.find((c) => String(c.countryCode) === String(code)) ?? null;
  reporterPicker.value = state.reporter?.countryCode ?? "";
  if (!state.reporter) return;
  remember("reporter", code);
  const search = new URLSearchParams(location.search);
  search.set("reporter", code);
  history.replaceState(null, "", `${location.pathname}?${search}${location.hash}`);
}

function start(section) {
  section.append(html(`
    <div class="head">
      <h1>${t("Choose a country")}</h1>
      <p class="lede">${t("Every page reads the trade of one country: who supplies its imports, where its exports go, and which sea routes carry them. Pick the country to start, and change it at any time from the header.")}</p>
    </div>
    <div class="panel"><div id="countries"></div></div>`));
  countryPicker(section.querySelector("#countries"), state.detail.countries, (c) => {
    chooseReporter(c.countryCode);
    render();
  });
}

async function render() {
  const [path, search] = location.hash.replace(/^#\/?/, "").split("?");
  const [name, ...rest] = path.split("/");
  const view = routes[name] ?? overview;
  document.querySelectorAll("[data-nav]").forEach((a) => {
    const active = routes[a.dataset.nav] === view;
    a.classList.toggle("active", active);
    if (active) {
      a.setAttribute("aria-current", "page");
      document.getElementById("current-page").textContent = a.textContent;
      menu.setAttribute("aria-label", `${t("Browse pages")}: ${a.textContent}`);
    } else a.removeAttribute("aria-current");
  });
  setMenu(false);
  disposeCharts();
  // A slow view keeps writing into its own detached section, never into the next one.
  const section = document.createElement("section");
  main.replaceChildren(section);
  window.scrollTo({ top: 0, behavior: "instant" });
  if (!state.snapshot) {
    section.innerHTML = `<div class="empty"><h1>${t("No snapshot yet")}</h1><p>${t("Prepare a BACI release first:")}</p>
      <pre>python -m atlas.prepare data/raw/BACI_HS12_V202601.zip</pre></div>`;
    return;
  }
  section.setAttribute("aria-busy", "true");
  section.dataset.loading = t("Loading trade data...");
  try {
    await snapshotDetail();
    reporterPicker.innerHTML = `<option value="">${t("Choose")}</option>${[...state.detail.countries]
      .sort((a, b) => a.countryName.localeCompare(b.countryName, lang))
      .map((c) => `<option value="${c.countryCode}">${esc(c.countryName)}</option>`).join("")}`;
    chooseReporter(state.reporter?.countryCode ?? new URLSearchParams(location.search).get("reporter") ?? remembered("reporter"));
    await (state.reporter ? view(section, rest, new URLSearchParams(search)) : start(section));
  } catch (error) {
    section.innerHTML = `<p class="error">${esc(error.message)}</p>`;
  } finally {
    section.removeAttribute("aria-busy");
  }
}

function showCitation() {
  const source = state.snapshot?.source;
  const geography = state.snapshot?.geography;
  const tariffs = state.snapshot?.tariffs;
  const categories = state.snapshot?.categories;
  document.getElementById("citation").innerHTML = source
    ? esc(t("Data: {name} {classification}, release {release}, {unit}. {citation} Licence: {license}.", {
        ...source,
        unit: t(source.valueUnit),
      })) + (geography ? ` ${esc(t("Geography: {name}, {distance}. {citation} Licence: {license}.", { ...geography, distance: t(geography.distance) }))}` : "")
      + (tariffs ? ` ${esc(t("Tariffs: {attribution}. {disclaimer}", { attribution: t(tariffs.attribution), disclaimer: t(tariffs.disclaimer) }))}` : "")
      + (categories ? ` ${esc(t("HS names: {name}. Licence: {license}.", categories))}` : "")
    : "";
}

document.querySelectorAll("[data-i18n]").forEach((node) => (node.textContent = t(node.textContent)));
navigation.setAttribute("aria-label", t("Main navigation"));
document.querySelectorAll("[data-lang]").forEach((button) => {
  button.classList.toggle("active", button.dataset.lang === lang);
  button.addEventListener("click", () => button.dataset.lang !== lang && switchLang(button.dataset.lang));
});

state.snapshots = await api("/snapshots");
const saved = remembered("snapshot");
state.snapshot = state.snapshots.find((s) => s._id === saved) ?? state.snapshots[0] ?? null;
picker.innerHTML = state.snapshots.map((s) => `<option value="${esc(s._id)}">${esc(s._id)}</option>`).join("");
if (state.snapshot) picker.value = state.snapshot._id;
picker.addEventListener("change", () => {
  state.snapshot = state.snapshots.find((s) => s._id === picker.value);
  remember("snapshot", picker.value);
  showCitation();
  render();
});
reporterPicker.addEventListener("change", () => {
  chooseReporter(reporterPicker.value);
  render();
});
window.addEventListener("hashchange", render);
showCitation();
render();
