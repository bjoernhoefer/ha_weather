"""Exercise Recorder history UI with Node and a small, offline DOM double."""

from pathlib import Path
import re
import shutil
import subprocess

import pytest


PAGE = Path(__file__).parents[1] / "app/static/index.html"


DOM = r"""
const assert = require("node:assert/strict");
class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.parentNode = null;
    this.open = false;
    this.disabled = false;
    this.hidden = false;
    this.className = "";
    this.classList = {add: name => { this.className += ` ${name}`; }};
    this.text = "";
  }
  get isConnected() { return this === root || !!this.parentNode?.isConnected; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return this.attributes[key] ?? null; }
  closest(tag) {
    if (this.tag === tag) return this;
    return this.parentNode?.closest(tag) ?? null;
  }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  append(...children) {
    for (const child of children) {
      if (typeof child === "string") this.children.push(document.createTextNode(child));
      else {
        child.remove();
        this.children.push(child);
        child.parentNode = this;
      }
    }
  }
  appendChild(child) { this.append(child); return child; }
  replaceChildren(...children) { this.textContent = ""; this.append(...children); }
  remove() {
    if (this.parentNode) {
      this.parentNode.children = this.parentNode.children.filter(child => child !== this);
      this.parentNode = null;
    }
  }
  set textContent(value) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this.text = String(value);
  }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(""); }
  set innerHTML(value) { throw new Error("History must not render untrusted HTML"); }
}
const Node = Element;
let svgCreations = 0;
const document = {
  createElement: tag => new Element(tag),
  createElementNS: (namespace, tag) => {
    assert.equal(namespace, "http://www.w3.org/2000/svg");
    if (tag === "svg") svgCreations++;
    return new Element(tag);
  },
  createTextNode: text => { const node = new Element("#text"); node.textContent = text; return node; },
};
const root = new Element("root");
const elements = {measurements: new Element("tbody")};
const measurementTable = new Element("table");
root.append(measurementTable);
measurementTable.append(elements.measurements);
const $ = id => elements[id];
const locationName = id => `Location ${id}`;
const OBS_ORIGINS = {ui: "web UI", environment: "environment"};
const requests = [];
const api = (path, options) => new Promise((resolve, reject) => {
  requests.push({path, options, reply: resolve, reject});
});
const settle = () => new Promise(resolve => setImmediate(resolve));
const descendants = element => element.children.flatMap(child => [child, ...descendants(child)]);
const tags = (element, tag) => descendants(element).filter(child => child.tag === tag);
const findButton = (element, label) => {
  const found = tags(element, "button").find(child => child.textContent === label);
  assert.ok(found, `Missing button: ${label}`);
  return found;
};
const click = element => {
  assert.equal(element.disabled, false, "button must be enabled");
  return element.listeners.click();
};
const payload = {instance_id: "home", location_id: "vienna", entity_id: "sensor.garden"};
const stamp = hour => `2026-10-25T${String(hour).padStart(2, "0")}:00:00Z`;
const sample = (hour, value, extra = {}) => ({timestamp: stamp(hour), value, ...extra});
const history = (samples = [], gaps = []) => ({
  start: stamp(0), end: stamp(23), samples, gaps,
});
const mount = () => {
  const panel = measurementHistory(payload);
  root.append(panel);
  return panel;
};
const open = panel => { panel.open = true; panel.listeners.toggle(); };
const rows = panel => tags(panel, "tbody").flatMap(body => body.children);
const assertFiniteChart = panel => {
  const svg = tags(panel, "svg");
  assert.equal(svg.length, 1);
  const chart = svg[0];
  assert.equal(chart.attributes.role, "img");
  assert.ok(chart.attributes["aria-label"] || tags(chart, "title").length,
    "chart needs an accessible name");
  for (const node of [chart, ...descendants(chart)]) {
    for (const [key, value] of Object.entries(node.attributes)) {
      assert.doesNotMatch(value, /NaN|Infinity|undefined/, `finite SVG ${key}`);
    }
  }
  return chart;
};
"""


@pytest.fixture
def run_ui():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to exercise the UI JavaScript")
    page = PAGE.read_text()
    helpers = re.search(
        r"      function button\(.*?(?=      let explanationRequest)",
        page, re.DOTALL,
    )
    diagnostics = re.search(
        r"      function diagnosticTime\(.*?(?=      \$\(\"measurementTest\"\)\.addEventListener)",
        page, re.DOTALL,
    )
    rendering = re.search(
        r"      function renderMeasurements\(ha\).*?(?=      function )",
        page, re.DOTALL,
    )
    assert helpers and diagnostics and rendering, "UI function extraction changed"

    def run(scenario):
        javascript = DOM + helpers.group() + diagnostics.group() + rendering.group()
        javascript += (
            "\n(async () => {\n" + scenario
            + "\n})().catch(error => { console.error(error); process.exitCode = 1; });"
        )
        result = subprocess.run(
            [node, "-e", javascript], capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr

    return run


def test_history_is_lazy_sorted_utc_and_preserves_only_in_window_records(run_ui):
    run_ui(r"""
const panel = mount();
assert.equal(requests.length, 0, "collapsed history must not fetch");
assert.equal(svgCreations, 0);
open(panel);
assert.equal(requests.length, 1);
assert.equal(requests[0].path, "/api/observation-sources/home-assistant/measurements/history");
assert.equal(requests[0].options.method, "POST");
assert.deepEqual(JSON.parse(requests[0].options.body), payload);
panel.listeners.toggle();
assert.equal(requests.length, 1, "a pending load must not be duplicated");
requests[0].reply(history([
  sample(23, -2), sample(0, -5), sample(3, 1),
  {timestamp: "2026-10-25T03:00:00+02:00", value: -4},
  sample(2, 999, {carried: true}), sample(4, null), sample(5, "99"),
  null, sample(6, Infinity), sample(7, NaN), {timestamp: "invalid", value: 1},
  {timestamp: "2026-10-24T23:59:59Z", value: 88},
  {timestamp: "2026-10-25T23:00:01Z", value: 88},
], [
  {timestamp: stamp(2), reason: "<script>private</script>"},
  null, {timestamp: "invalid"}, {timestamp: "2026-10-24T23:00:00Z"},
]));
await settle();
assert.equal(svgCreations, 0, "loading history must not construct even a hidden SVG");
assert.equal(tags(panel, "ol").length, 0, "history is unnumbered");
assert.equal(tags(panel, "th").length, 2, "only datetime and temperature columns");
assert.match(tags(panel, "th")[0].textContent, /UTC/);
assert.match(tags(panel, "th")[1].textContent, /Temperature.*°C/);
assert.equal(rows(panel).length, 5);
const tableRows = rows(panel).map(row => tags(row, "td").map(td => td.textContent));
assert.deepEqual(tableRows.map(row => row[0]), [0, 1, 2, 3, 23].map(hour =>
  `2026-10-25 ${String(hour).padStart(2, "0")}:00:00 UTC`));
assert.match(tableRows[0][1], /-5/);
assert.match(tableRows[2][1], /Gap|unavailable|unusable/i);
assert.doesNotMatch(tableRows.flat().join(" "), /999|88|<script>|99/);
click(findButton(panel, "Show temperature trend"));
assertFiniteChart(panel);
assert.equal(requests.length, 1, "chart uses the loaded response, not another fetch");
panel.open = false;
panel.listeners.toggle();
open(panel);
assert.equal(requests.length, 1, "reopening loaded history reuses its data");
""")


@pytest.mark.parametrize("values", [[-5], [4, 4, 4], [-9, -3, -6]])
def test_chart_single_constant_and_negative_values_have_finite_geometry(run_ui, values):
    run_ui(f"""
const panel = mount();
open(panel);
requests[0].reply(history({values!r}.map((value, index) => sample(index, value))));
await settle();
assert.equal(svgCreations, 0);
click(findButton(panel, "Show temperature trend"));
const chart = assertFiniteChart(panel);
assert.ok(tags(chart, "circle").length || tags(chart, "polyline").length || tags(chart, "path").length,
  "valid temperatures must have visible geometry");
assert.equal(requests.length, 1);
""")


def test_chart_segments_break_at_gaps_and_use_timestamp_spacing(run_ui):
    run_ui(r"""
const panel = mount();
open(panel);
requests[0].reply(history([
  sample(22, -4), sample(0, -2), sample(1, -3), sample(20, -5),
  sample(8, -8), sample(9, -9), sample(10, -10), sample(12, -12),
], [{timestamp: stamp(4)}, {timestamp: stamp(9)}, {timestamp: stamp(11)}]));
await settle();
click(findButton(panel, "Show temperature trend"));
const chart = assertFiniteChart(panel);
const circles = tags(chart, "circle");
assert.equal(circles.length, 8, "no synthetic/carried points");
const x = circles.map(circle => Number(circle.attributes.cx));
assert.ok(x.every(Number.isFinite));
assert.ok(x[1] - x[0] < x[2] - x[1], "x spacing follows elapsed time, not row number");
assert.deepEqual(tags(chart, "polyline").map(line => line.attributes.points.split(" ").length),
  [2, 3], "gaps split lines, including samples exactly at a gap time");
const linePoints = tags(chart, "polyline").map(line => line.attributes.points.split(" ")
  .map(pair => Number(pair.split(",")[0])));
assert.deepEqual(linePoints[0], x.slice(0, 2));
assert.deepEqual(linePoints[1], x.slice(5), "isolated points are not joined through a gap");
assert.equal(requests.length, 1);
""")


def test_empty_history_and_zero_duration_singleton(run_ui):
    run_ui(r"""
const panel = mount();
open(panel);
requests[0].reply(history());
await settle();
assert.equal(rows(panel).length, 0);
assert.equal(svgCreations, 0);
assert.match(panel.textContent, /No usable Celsius/);
assert.equal(findButton(panel, "Show temperature trend").disabled, true);
const pending = click(findButton(panel, "Refresh history"));
requests[1].reply({...history([sample(0, 0)]), end: stamp(0)});
await pending;
click(findButton(panel, "Show temperature trend"));
const chart = assertFiniteChart(panel);
assert.equal(tags(chart, "circle").length, 1);
""")


@pytest.mark.parametrize("response", [
    "{}",
    "{...history(), samples: null}",
    "{...history(), start: 'invalid'}",
    "{...history(), end: stamp(0), start: stamp(1)}",
])
def test_invalid_history_response_does_not_leave_stale_chart(run_ui, response):
    run_ui(f"""
const panel = mount();
open(panel);
requests[0].reply(history([sample(0, 10)]));
await settle();
click(findButton(panel, "Show temperature trend"));
assertFiniteChart(panel);
const pending = click(findButton(panel, "Refresh history"));
requests[1].reply({response});
await pending;
assert.equal(tags(panel, "svg").length, 0);
assert.equal(rows(panel).length, 0);
assert.match(panel.textContent, /History unavailable/);
assert.equal(findButton(panel, "Retry history").disabled, false);
assert.equal(findButton(panel, "Show temperature trend").disabled, true);
""")


def test_refresh_clears_chart_on_success_error_and_empty_response(run_ui):
    run_ui(r"""
const panel = mount();
open(panel);
requests[0].reply(history([sample(0, 1), sample(1, 2)]));
await settle();
click(findButton(panel, "Show temperature trend"));
assertFiniteChart(panel);
const refresh = findButton(panel, "Refresh history");
let pending = click(refresh);
assert.equal(tags(panel, "svg").length, 0, "clear old SVG as soon as refresh starts");
assert.equal(rows(panel).length, 0, "clear outdated table immediately");
assert.equal(refresh.disabled, true);
requests[1].reply(history([sample(2, -8)]));
await pending;
assert.equal(tags(panel, "svg").length, 0, "refresh must require a new explicit chart click");
click(findButton(panel, "Show temperature trend"));
assertFiniteChart(panel);
pending = click(refresh);
requests[2].reject(new Error("504: credential-sentinel"));
await pending;
assert.equal(tags(panel, "svg").length, 0);
assert.equal(rows(panel).length, 0);
assert.doesNotMatch(panel.textContent, /credential-sentinel/);
assert.match(panel.textContent, /Retry|retry/);
pending = click(findButton(panel, "Retry history"));
requests[3].reply(history([], [{timestamp: stamp(2)}]));
await pending;
assert.equal(tags(panel, "svg").length, 0);
assert.equal(rows(panel).length, 1, "gap-only responses still show recorded gaps");
assert.match(panel.textContent, /No usable Celsius/);
const show = tags(panel, "button").find(button => button.textContent === "Show temperature trend");
assert.ok(!show || show.disabled, "no chart can be requested without usable temperatures");
""")


@pytest.mark.parametrize("failure", [False, True])
def test_detached_history_ignores_pending_response(run_ui, failure):
    run_ui(f"""
const panel = mount();
open(panel);
panel.remove();
const before = panel.textContent;
const beforeNodes = descendants(panel).length;
requests[0].{"reject(new Error('credential-sentinel'))" if failure else "reply(history([sample(0, 10)]))"};
await settle();
assert.equal(panel.textContent, before, "detached status must not be updated");
assert.equal(descendants(panel).length, beforeNodes);
assert.equal(svgCreations, 0);
""")


def test_measurement_history_has_its_own_full_width_row(run_ui):
    run_ui(r"""
const measurements = [
  {id: "one", ...payload, name: "Garden", scope: "outdoor", origin: "ui"},
  {id: "two", ...payload, name: "Outside", scope: "outdoor", origin: "environment"},
];
renderMeasurements({instances: [{id: "home", name: "Home"}], measurements});
const body = $("measurements");
assert.equal(body.children.length, 4, "each measurement has metadata and history rows");
for (let index = 0; index < measurements.length; index++) {
  const metadata = body.children[index * 2];
  const historyRow = body.children[index * 2 + 1];
  assert.equal(tags(metadata, "details").length, 0, "do not squeeze history into actions");
  assert.equal(metadata.children.length, 7);
  assert.equal(historyRow.children.length, 1);
  assert.equal(historyRow.children[0].colSpan, metadata.children.length);
  assert.equal(tags(historyRow, "details").length, 1);
  assert.ok(findButton(metadata, "Test"));
}
assert.equal(requests.length, 0);
assert.equal(svgCreations, 0);
const oldPanel = tags(body, "details")[0];
open(oldPanel);
renderMeasurements({instances: [], measurements: []});
assert.equal(oldPanel.isConnected, false, "configuration rerender detaches old panels");
requests[0].reply(history([sample(0, 12)]));
await settle();
assert.equal(tags(oldPanel, "tbody")[0].children.length, 0,
  "pending results cannot populate an obsolete measurement row");
""")
