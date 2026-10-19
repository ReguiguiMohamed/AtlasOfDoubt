import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

globalThis.location = new URL("http://localhost/?lang=en");
const elements = [];
globalThis.document = {
  documentElement: {}, fonts: { ready: Promise.resolve() }, body: { append() {} },
  createElement: (tag) => {
    const element = { tag, addEventListener(name, callback) { this[name] = callback; }, click() { this.clicked = true; }, remove() {} };
    elements.push(element);
    return element;
  },
};
globalThis.window = { addEventListener() {} };
globalThis.matchMedia = (query) => ({ matches: query === "(pointer: fine)", addEventListener() {} });
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "#14213d" });
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.echarts = {
  init: () => ({
    setOption(option) { this.option = option; },
    getZr() { return { on: (name, callback) => { this[name] = callback; } }; },
    dispatchAction(action) { this.action = action; },
    getDataURL(options) { this.exportOptions = options; return "data:image/png;base64,test"; },
    dispose() {},
    resize() {},
  }),
};

const { api, chart, disposeCharts, preload, relativeRanks } = await import("../atlas/static/lib.js");
const node = () => ({ append() {} });
afterEach(disposeCharts);

test("long toolbox help uses a confined HTML tooltip instead of canvas titles", () => {
  const { option } = chart(node(), {
    xAxis: { type: "category" }, yAxis: { type: "value" }, series: [{ type: "line" }],
  });
  assert.equal(option.toolbox.showTitle, false);
  assert.equal(option.toolbox.tooltip.show, true);
  assert.equal(option.toolbox.tooltip.confine, true);
  assert.equal(option.toolbox.tooltip.formatter({ title: "<Zoom>" }), "&lt;Zoom&gt;");
  assert.match(option.tooltip.extraCssText, /white-space:normal/);
});

test("legends and plots leave room for a separate toolbar row", () => {
  const { option } = chart(node(), {
    grid: { top: 10, left: 70 }, legend: {},
    xAxis: { type: "category" }, yAxis: { type: "value" }, series: [{ type: "line" }],
  });
  assert.ok(option.legend.top > option.toolbox.top + option.toolbox.itemSize);
  assert.ok(option.grid.top > option.legend.top + 20);
  assert.equal(option.legend.type, "scroll");
  assert.equal(option.xAxis[0].axisLabel.hideOverlap, true);
});

test("a scatter overlay on bars cannot zoom away the value baseline", () => {
  const { option } = chart(node(), {
    xAxis: { type: "category" }, yAxis: { type: "value" },
    series: [{ type: "bar" }, { type: "scatter" }],
  });
  assert.deepEqual(option.toolbox.feature.dataZoom.xAxisIndex, [0]);
  assert.equal(option.toolbox.feature.dataZoom.yAxisIndex, false);
  assert.equal(option.dataZoom.length, 1);
});

test("scatter charts zoom both axes and double-click restores the full range", () => {
  const instance = chart(node(), {
    xAxis: { type: "value" }, yAxis: { type: "value" }, series: [{ type: "scatter" }],
  });
  assert.equal(instance.option.dataZoom.length, 2);
  assert.equal(instance.option.dataZoom[0].zoomOnMouseWheel, "ctrl");
  assert.equal(instance.option.dataZoom[0].moveOnMouseWheel, false);
  instance.dblclick();
  assert.deepEqual(instance.action, { type: "dataZoom", start: 0, end: 100 });
});

test("narrow bar charts truncate country labels and preserve the category axis", () => {
  const { option } = chart(node(), {
    grid: { left: 140, right: 70 }, xAxis: { type: "value" },
    yAxis: { type: "category", inverse: true, data: ["A long country name"] }, series: [{ type: "bar" }],
  });
  assert.equal(option.yAxis[0].inverse, true);
  assert.equal(option.yAxis[0].axisLabel.overflow, "truncate");
  assert.ok(option.media[0].option.grid.left < option.grid.left);
  assert.ok(option.media[0].option.yAxis[0].axisLabel.width < option.media[0].option.grid.left);
  assert.equal(option.media[1].option.grid.left, 140);
  assert.equal(option.media[1].option.yAxis[0].axisLabel.width, 124);
});

test("the save button downloads one named PNG without chart controls", () => {
  const instance = chart({ id: "suppliers", append() {} }, {
    xAxis: { type: "category" }, yAxis: { type: "value" }, series: [{ type: "bar" }],
  });
  const save = elements.at(-1);
  assert.equal(save.tag, "button");
  const linksBefore = elements.filter((e) => e.tag === "a").length;
  save.click();
  const link = elements.at(-1);
  assert.equal(link.download, "AtlasOfDoubt-suppliers.png");
  assert.equal(link.href, "data:image/png;base64,test");
  assert.equal(link.clicked, true);
  assert.equal(elements.filter((e) => e.tag === "a").length, linksBefore + 1);
  assert.equal(instance.exportOptions.pixelRatio, 2);
  assert.deepEqual(instance.exportOptions.excludeComponents, ["toolbox"]);
});

test("close similarity scores span the palette while ties keep the same color", () => {
  const values = [0.700002, 0.7, 0.700001, 0.700001];
  assert.deepEqual([...relativeRanks(values)], [[0.7, 0], [0.700001, 0.5], [0.700002, 1]]);
  assert.deepEqual(values, [0.700002, 0.7, 0.700001, 0.700001]);
  assert.deepEqual([...relativeRanks([0.7, 0.7])], [[0.7, 0.5]]);
  assert.equal(relativeRanks([]).size, 0);
});

test("snapshot answers are fetched once and each reader gets its own copy", async () => {
  const asked = [];
  globalThis.fetch = async (url, options) => {
    asked.push(`${options.method ?? "GET"} ${url}`);
    if (url.includes("broken")) return { ok: false, status: 503, statusText: "Busy", json: async () => ({}) };
    return { ok: true, json: async () => ({ rows: [1, 2] }) };
  };
  await preload(["/exports?snapshot=s&reporter=1"]);
  const first = await api("/exports?snapshot=s&reporter=1");
  first.rows.push(3);
  assert.deepEqual((await api("/exports?snapshot=s&reporter=1")).rows, [1, 2]);
  await assert.rejects(api("/broken?snapshot=s"));
  await assert.rejects(api("/broken?snapshot=s"));
  await api("/reports?reporter=1");
  await api("/reports?reporter=1");
  await api("/scenarios/preview?snapshot=s", { method: "POST" });
  await api("/scenarios/preview?snapshot=s", { method: "POST" });
  assert.deepEqual(asked, [
    "GET /api/exports?snapshot=s&reporter=1",
    "GET /api/broken?snapshot=s", "GET /api/broken?snapshot=s",
    "GET /api/reports?reporter=1", "GET /api/reports?reporter=1",
    "POST /api/scenarios/preview?snapshot=s", "POST /api/scenarios/preview?snapshot=s",
  ]);
});
