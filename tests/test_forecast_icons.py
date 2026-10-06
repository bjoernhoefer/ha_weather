"""Exercise the forecast UI JavaScript using Node's built-in assertions."""

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from app.providers.conditions import WMO_CODES


def test_hourly_forecast_icons():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to exercise the UI JavaScript")

    page = (Path(__file__).parents[1] / "app/static/index.html").read_text()
    script = re.search(
        r"      function forecastIcon\(condition\) \{.*?(?=      const KEY_ORIGINS)",
        page,
        re.DOTALL,
    ).group()
    conditions = sorted(set(WMO_CODES.values()) - {"unknown"})
    javascript = r"""
const assert = require("node:assert/strict");
class Element {
  constructor(tag) {
    this.tag = tag;
    this.attributes = {};
    this.children = [];
    this.classList = { add: (name) => { this.className = name; } };
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.append(child); }
  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return this.text; }
}
const document = {
  createElement: (tag) => new Element(tag),
  createElementNS: (namespace, tag) => {
    assert.equal(namespace, "http://www.w3.org/2000/svg");
    return new Element(tag);
  },
};
const bodies = { hourlyForecast: new Element("div"), fourHourlyForecast: new Element("tbody") };
const $ = (id) => bodies[id];
const fmt = (value) => value == null ? null : Number(value).toFixed(1);
const cell = (row, value) => {
  const element = document.createElement("td");
  element.textContent = value;
  row.appendChild(element);
};
"""
    javascript += script
    javascript += f"\nconst conditions = {json.dumps(conditions)};\n"
    javascript += r"""
conditions.push("sunny", "clear-night", "snowy-rainy", "hail", "windy", "windy-variant", "exceptional");
const fallback = forecastIcon(null).children[0].attributes.d;
for (const condition of conditions) {
  const icon = forecastIcon(condition);
  assert.equal(icon.tag, "svg");
  assert.equal(icon.className, "forecast-icon");
  assert.equal(icon.attributes["aria-hidden"], "true");
  assert.equal(icon.attributes.focusable, "false");
  assert.equal(icon.attributes.viewBox, "0 0 24 24");
  assert.equal(icon.attributes.stroke, "currentColor");
  assert.equal(icon.children.length, 1);
  assert.equal(icon.children[0].tag, "path");
  assert.notEqual(icon.children[0].attributes.d, fallback, condition);
}
for (const condition of [undefined, "", "unknown", "unexpected", "__proto__", "constructor", "toString", "<img src=x onerror=alert(1)>"]) {
  assert.equal(forecastIcon(condition).children[0].attributes.d, fallback);
}
assert.notEqual(forecastIcon("clear").children[0].attributes.d, forecastIcon("rainy").children[0].attributes.d);
const items = conditions.map((condition) => ({
  target_time: "2026-10-06T12:00:00Z", temperature: 14.7, condition,
  precipitation_mm: 0, wind_speed: 3.5, provider_count: 7,
}));
renderShortForecast(items, "hourlyForecast");
assert.equal(bodies.hourlyForecast.children.length, items.length);
for (const [index, card] of bodies.hourlyForecast.children.entries()) {
  assert.equal(card.className, "hour-card");
  assert.equal(card.children[0].dateTime, items[index].target_time);
  const row = card.children[1];
  assert.equal(row.className, "temperature-row");
  assert.equal(row.children[0].textContent, "14.7°");
  assert.equal(row.children[1].tag, "svg");
  assert.equal(card.children[2].textContent, items[index].condition);
  assert.deepEqual(card.children[3].children.map((line) => line.textContent),
    ["Rain 0.0 mm", "Wind 3.5", "7 provider(s)"]);
}
renderShortForecast([{...items[0], condition: null, temperature: null}], "hourlyForecast");
assert.equal(bodies.hourlyForecast.children.length, 1);
assert.equal(bodies.hourlyForecast.children[0].children[1].children[0].textContent, "–°");
assert.equal(bodies.hourlyForecast.children[0].children[2].textContent, "—");
renderShortForecast(items, "fourHourlyForecast");
assert.equal(bodies.fourHourlyForecast.children.length, items.length);
assert.equal(bodies.fourHourlyForecast.children[0].children.length, 6);
assert.equal(bodies.fourHourlyForecast.children[0].children[4].textContent, items[0].condition);
renderShortForecast([], "hourlyForecast");
assert.equal(bodies.hourlyForecast.children.length, 0);
"""
    result = subprocess.run(
        [node, "-e", javascript], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
