"""Exercise the activity panel independently of a running backend."""

from pathlib import Path
import re
import shutil
import subprocess

import pytest


PAGE = Path(__file__).parents[1] / "app/static/index.html"


def test_activity_panel_markup():
    page = PAGE.read_text()
    assert re.search(
        r'id="settingsSection".*?</details>\s*'
        r'<details class="fold" id="loggingSection">',
        page,
        re.DOTALL,
    )
    assert '<a href="#loggingSection">Logging</a>' in page
    assert '<label for="logsLevel">Minimum severity' in page
    assert 'id="logsStatus" class="muted" role="status" aria-live="polite"' in page
    assert 'id="logsList" class="log-list" aria-label="Recent activity"' in page


def test_activity_panel_requests_and_rendering():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to exercise the UI JavaScript")
    page = PAGE.read_text()
    api_script = re.search(
        r"      function errorText\(detail\).*?(?=      let logsRequest)",
        page,
        re.DOTALL,
    ).group()
    logs_script = re.search(
        r"      let logsRequest.*?(?=      function button)",
        page,
        re.DOTALL,
    ).group()
    javascript = r"""
const assert = require("node:assert/strict");
class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.open = false;
    this.disabled = false;
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.append(child); }
  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return this.text; }
  set innerHTML(value) { throw new Error("Unsafe HTML rendering"); }
  focus() { this.focused = true; }
}
const document = { createElement: tag => new Element(tag) };
const elements = Object.fromEntries(
  ["loggingSection", "logsLevel", "refreshLogs", "logsStatus", "logsList", "settingsSection", "apiKey"]
  .map(id => [id, new Element(id)])
);
const $ = id => elements[id];
$("logsLevel").value = "INFO";
const apiKeyInput = $("apiKey");
const storedApiKey = () => "test-key";
const requests = [];
const fetch = (path, options) => new Promise((resolve, reject) => {
  requests.push({
    path, options, reject,
    reply: (data, status = 200) => resolve({
      ok: status === 200, status,
      json: async () => data, text: async () => JSON.stringify({detail: data})
    })
  });
});
const settle = () => new Promise(resolve => setImmediate(resolve));
const entry = {
  timestamp: "2026-10-09T08:30:00+02:00", level: "WARNING",
  component: "<img src=x onerror=alert(1)>", message: "<script>secret</script>\n" + "x".repeat(500)
};
"""
    javascript += api_script + logs_script
    javascript += r"""
(async () => {
  assert.equal(requests.length, 0, "collapsed panel does not fetch");
  $("loggingSection").open = true;
  $("loggingSection").listeners.toggle();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].path, "/api/logs?level=INFO&limit=100");
  assert.equal(requests[0].options.cache, "no-store");
  assert.equal(requests[0].options.headers["X-API-Key"], "test-key");
  assert.match($("logsStatus").textContent, /Loading/);
  assert.equal($("logsList").attributes["aria-busy"], "true");
  assert.equal($("refreshLogs").disabled, true);
  requests[0].reply(Array.from({length: 110}, (_, i) => ({...entry, message: `${i} ${entry.message}`})));
  await settle();
  assert.equal($("logsList").children.length, 100);
  const first = $("logsList").children[0];
  assert.equal(first.children[0].children[0].textContent, "2026-10-09 06:30:00 UTC");
  assert.equal(first.children[0].children[1].textContent, "WARNING");
  assert.equal(first.children[0].children[2].textContent, entry.component);
  assert.equal(first.children[1].textContent, `0 ${entry.message}`);
  assert.equal($("logsList").children[99].children[1].textContent, `99 ${entry.message}`);
  assert.equal($("refreshLogs").disabled, false);
  assert.equal($("logsList").attributes["aria-busy"], "false");
  $("loggingSection").open = false;
  $("loggingSection").listeners.toggle();
  assert.equal(requests.length, 1, "closing does not fetch");
  $("loggingSection").open = true;
  $("loggingSection").listeners.toggle();
  assert.equal(requests.length, 2, "reopening fetches the latest entries");
  requests[1].reply([entry]);
  await settle();
  assert.equal($("logsList").children.length, 1);

  $("logsLevel").value = "WARNING";
  const old = $("logsLevel").listeners.change();
  $("logsLevel").value = "ERROR";
  const latest = $("logsLevel").listeners.change();
  assert.equal(requests[2].path, "/api/logs?level=WARNING&limit=100");
  assert.equal(requests[3].path, "/api/logs?level=ERROR&limit=100");
  assert.equal($("logsList").children.length, 0, "clear outdated filter results");
  requests[3].reply([]);
  await latest;
  assert.match($("logsStatus").textContent, /No recent activity matches/);
  requests[2].reply([entry]);
  await old;
  assert.equal($("logsList").children.length, 0, "ignore stale successes");

  const staleFailure = $("refreshLogs").listeners.click();
  const newRequest = $("logsLevel").listeners.change();
  requests[4].reject(new Error("credential-sentinel"));
  await staleFailure;
  assert.match($("logsStatus").textContent, /Loading/);
  assert.equal($("refreshLogs").disabled, true, "stale finally cannot reset loading");
  requests[5].reply([{timestamp: "invalid", level: "ERROR", component: null, message: null}]);
  await newRequest;
  const fallback = $("logsList").children[0];
  assert.equal(fallback.children[0].children[0].textContent, "Time unavailable (UTC)");
  assert.equal(fallback.children[0].children[2].textContent, "Unknown component");
  assert.equal(fallback.children[1].textContent, "No summary available.");

  $("logsLevel").value = "INFO";
  const empty = $("logsLevel").listeners.change();
  requests[6].reply([]);
  await empty;
  assert.equal($("logsStatus").textContent, "No recent activity yet.");
  const failure = $("refreshLogs").listeners.click();
  requests[7].reply("credential-sentinel", 500);
  await failure;
  assert.match($("logsStatus").textContent, /Unable to load/);
  assert.ok(!$("logsStatus").textContent.includes("credential-sentinel"));
  assert.equal($("logsList").children.length, 0);
  const unauthorized = $("refreshLogs").listeners.click();
  requests[8].reply("credential-sentinel", 401);
  await unauthorized;
  assert.equal($("settingsSection").open, true);
  assert.equal(apiKeyInput.focused, true, "reuse existing 401 behavior");
  assert.ok(!$("logsStatus").textContent.includes("credential-sentinel"));
  const invalid = $("refreshLogs").listeners.click();
  requests[9].reply({message: "credential-sentinel"});
  await invalid;
  assert.match($("logsStatus").textContent, /Unable to load/);
  assert.ok(!$("logsStatus").textContent.includes("credential-sentinel"));
  assert.ok(!String(loadLogs).includes("setInterval"), "no log polling");
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        [node, "-e", javascript], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
