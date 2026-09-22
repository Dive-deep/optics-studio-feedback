/* Request-order and snapshot tests, written before the controller fixes. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../design/file-controller.js"), "utf8");
const copy = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(setImmediate);
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function report(name) {
  return {status: "valid", report_path: name + ".json", database_path: name + ".db",
    model_path: name + ".pth", suggested_case_id: name};
}
function session(name) {
  return {status: "loaded", path: name + "-session.json",
    state: {tag: name, target_snapshot: {profile_id: name + "-target"}},
    references: {report_path: name + ".json", database_path: name + ".db", target_path: name + "-target.json"},
    warnings: [], resume_jobs: false};
}
function target(name) {
  return {status: "loaded", path: name + "-target.json", profile: {profile_id: name}, read_only: true};
}
function harness(overrides = {}) {
  const calls = [], notices = [], errors = [], changes = [], applies = [];
  let displayed = null, reportListener, reportStartedListener;
  const request = async (method, params) => {
    calls.push({method, params});
    if (overrides[method]) return overrides[method](params);
    if (method === "load_report") return report(params.path.split(".")[0]);
    if (method === "list_cases") return {cases: [{id: params.path.split(".")[0], status: "SUCCESS", ui_compatible: true}]};
    if (method === "load_case") return {id: params.case_id};
    if (method === "choose_session_save") return {status: "saved", path: "saved-session.json"};
    if (method === "export_bundle") return {status: "exported", path: "saved.zip"};
    throw new Error("Unexpected call: " + method);
  };
  const window = {opticsBridge: {request, onReportLoaded: listener => { reportListener = listener; }}};
  if (!overrides.noDropStarted) {
    window.opticsBridge.onReportLoadStarted = listener => { reportStartedListener = listener; };
  }
  vm.runInNewContext(source, {window});
  const controller = window.createOpticsFileController({
    contextChanged: context => changes.push(copy(context)),
    notice: message => notices.push(message),
    error: error => errors.push(error),
    snapshot: () => overrides.snapshot ? overrides.snapshot()
      : {tag: displayed, reference_data: {id: displayed}},
    restore: state => { if (state.invalid) throw new Error("Invalid snapshot"); displayed = state.tag; },
    applyCase: data => { displayed = data.id; applies.push(data.id); }
  });
  return {controller, calls, notices, errors, changes, applies,
    displayed: () => displayed,
    startReport: id => reportStartedListener?.({id}),
    emitReport: (record, id) => reportListener({id, ok: true, data: record}),
    emitReportError: (id, code) => reportListener({id, ok: false, error: {code, message: "Drop failed"}})};
}

test("a slower earlier loadReport cannot replace a newer report", async () => {
  const old = deferred();
  const h = harness({load_report: p => p.path === "A.json" ? old.promise : report("B")});
  const first = h.controller.loadReport("A.json");
  await tick();
  await h.controller.loadReport("B.json");
  old.resolve(report("A"));
  assert.equal(await first, null);
  assert.equal(h.displayed(), "B");
  assert.equal(h.controller.getContext().references.report_path, "B.json");
  assert.deepEqual(h.applies, ["B"]);
});

test("openReport takes ownership before its native dialog/file result arrives", async () => {
  const old = deferred();
  let count = 0;
  const h = harness({choose_report: () => ++count === 1 ? old.promise : report("B")});
  const first = h.controller.openReport();
  await tick();
  await h.controller.openReport();
  old.resolve(report("A"));
  assert.equal(await first, null);
  assert.equal(h.displayed(), "B");
});

test("stale report stops before requesting its case after list_cases resolves", async () => {
  const oldList = deferred();
  const h = harness({list_cases: p => p.path === "A.db" ? oldList.promise
    : {cases: [{id: "B", status: "SUCCESS", ui_compatible: true}]}});
  const first = h.controller.loadReport("A.json");
  await tick();
  await h.controller.loadReport("B.json");
  oldList.resolve({cases: [{id: "A", status: "SUCCESS", ui_compatible: true}]});
  assert.equal(await first, null);
  assert.equal(h.calls.filter(c => c.method === "load_case" && c.params.case_id === "A").length, 0);
  assert.equal(h.displayed(), "B");
});

test("a late session metadata response cannot overwrite the newer context case list", async () => {
  const oldMetadata = deferred();
  let opened = 0;
  const h = harness({choose_session_open: () => session(++opened === 1 ? "A" : "B"),
    load_report: p => p.path === "A.json" ? oldMetadata.promise : report("B")});
  const opening = h.controller.open();
  await tick();
  await h.controller.open();
  oldMetadata.resolve(report("A"));
  assert.equal(await opening, null);
  const context = h.controller.getContext();
  assert.equal(context.references.database_path, "B.db");
  assert.deepEqual(copy(context.cases), [{id: "B", status: "SUCCESS", ui_compatible: true}]);
  assert.equal(h.displayed(), "B");
});

test("a session result requested earlier cannot replace a newer report", async () => {
  const old = deferred();
  const h = harness({choose_session_open: () => old.promise});
  const first = h.controller.open();
  await tick();
  await h.controller.loadReport("B.json");
  old.resolve(session("A"));
  assert.equal(await first, null);
  assert.equal(h.displayed(), "B");
});

test("a stale selected-case response does not mutate a newer report workspace", async () => {
  const old = deferred();
  const h = harness({load_case: p => p.case_id === "A2" ? old.promise : {id: p.case_id}});
  await h.controller.loadReport("A.json");
  const selecting = h.controller.selectCase("A2");
  await tick();
  await h.controller.loadReport("B.json");
  old.resolve({id: "A2"});
  assert.equal(await selecting, null);
  assert.equal(h.displayed(), "B");
});

test("stale failed operations do not open an error over a newer successful load", async () => {
  const old = deferred();
  const h = harness({load_report: p => p.path === "A.json" ? old.promise : report("B")});
  const first = h.controller.loadReport("A.json");
  await tick();
  await h.controller.loadReport("B.json");
  old.reject(new Error("Old file failed"));
  assert.equal(await first, null);
  assert.equal(h.errors.length, 0);
});

test("target selection has its own request order", async () => {
  const old = deferred();
  let count = 0;
  const h = harness({choose_target: () => ++count === 1 ? old.promise : target("B")});
  const first = h.controller.openTarget();
  await tick();
  await h.controller.openTarget();
  old.resolve(target("A"));
  assert.equal(await first, null);
  assert.equal(h.controller.getContext().target.profile.profile_id, "B");
});

test("opening a workspace invalidates an earlier pending target selection", async () => {
  const old = deferred();
  const h = harness({choose_target: () => old.promise, choose_session_open: () => session("B")});
  const first = h.controller.openTarget();
  await tick();
  await h.controller.open();
  old.resolve(target("A"));
  assert.equal(await first, null);
  assert.equal(h.controller.getContext().target.profile.profile_id, "B-target");
});

test("loading a report does not cancel an independent target selection", async () => {
  const pending = deferred();
  const h = harness({choose_target: () => pending.promise});
  const selecting = h.controller.openTarget();
  await tick();
  await h.controller.loadReport("B.json");
  pending.resolve(target("A"));
  await selecting;
  assert.equal(h.controller.getContext().references.report_path, "B.json");
  assert.equal(h.controller.getContext().references.target_path, "A-target.json");
});

test("target chosen after a pending session open is preserved", async () => {
  const opening = deferred();
  const h = harness({choose_session_open: () => opening.promise, choose_target: () => target("B")});
  const first = h.controller.open();
  await tick();
  await h.controller.openTarget();
  opening.resolve(session("A"));
  await first;
  assert.equal(h.controller.getContext().references.report_path, "A.json");
  assert.equal(h.controller.getContext().references.target_path, "B-target.json");
  assert.equal(h.controller.getContext().target.profile.profile_id, "B");
});

test("restore validation error leaves previous file context intact", async () => {
  const bad = session("A");
  bad.state.invalid = true;
  const h = harness({choose_session_open: () => bad});
  await h.controller.loadReport("B.json");
  assert.equal(await h.controller.open(), null);
  assert.equal(h.controller.getContext().references.database_path, "B.db");
  assert.equal(h.displayed(), "B");
  assert.equal(h.errors.length, 1);
});

test("save captures a coherent copy of references even when target changes later", async () => {
  const pending = deferred();
  let count = 0;
  const h = harness({choose_target: () => target(++count === 1 ? "A" : "B"),
    choose_session_save: () => pending.promise});
  await h.controller.openTarget();
  const saving = h.controller.save();
  const params = h.calls.find(c => c.method === "choose_session_save").params;
  await h.controller.openTarget();
  assert.equal(params.references.target_path, "A-target.json");
  assert.equal(params.state.target_snapshot.profile_id, "A");
  pending.resolve({status: "saved", path: "saved-session.json"});
  await saving;
});

test("export notice describes selected files and settings, including settings-only exports", async () => {
  const h = harness();
  await h.controller.exportBundle();
  assert.match(h.notices.at(-1), /선택한 파일과 Workspace 설정을 ZIP으로 내보냈습니다/);
});

function missingReportSession(name = "A") {
  const result = session(name);
  result.warnings = [{code: "MISSING_REFERENCE", message: "report_path needs to be relinked: " + name + ".json."}];
  return result;
}
function relinkHarness(overrides = {}) {
  return harness({
    choose_session_open: () => missingReportSession(),
    choose_report: () => report("B"),
    list_cases: p => ({cases: p.path === "B.db"
      ? [{id: "A", status: "SUCCESS", ui_compatible: true}, {id: "B", status: "SUCCESS", ui_compatible: true}]
      : [{id: "A", status: "SUCCESS", ui_compatible: true}]}),
    ...overrides
  });
}

test("browsing a missing restored report relinks without applying a DB case", async () => {
  const h = relinkHarness();
  await h.controller.open();
  assert.equal(h.controller.getContext().report, null);
  const before = h.displayed();
  await h.controller.openReport();
  assert.equal(h.displayed(), before);
  assert.deepEqual(h.applies, []);
  assert.equal(h.calls.filter(c => c.method === "load_case").length, 0);
  assert.equal(h.controller.getContext().references.report_path, "B.json");
  assert.equal(h.controller.getContext().references.database_path, "B.db");
  assert.equal(h.controller.getContext().sessionPath, "A-session.json");
  assert.match(h.notices.at(-1), /다시 연결/);
});

test("native drop also relinks a missing restored report without resetting edits", async () => {
  const h = relinkHarness();
  await h.controller.open();
  h.startReport("drop-relink");
  h.emitReport(report("B"), "drop-relink");
  await tick();
  assert.equal(h.displayed(), "A");
  assert.deepEqual(h.applies, []);
  assert.equal(h.controller.getContext().report.report_path, "B.json");
});

test("relink rejects an absent or incompatible saved reference case and preserves context", async () => {
  for (const replacementCases of [[{id: "B", ui_compatible: true}], [{id: "A", ui_compatible: false}]]) {
    const h = relinkHarness({list_cases: p => ({cases: p.path === "B.db"
      ? replacementCases : [{id: "A", ui_compatible: true}]})});
    await h.controller.open();
    const before = copy(h.controller.getContext());
    assert.equal(await h.controller.openReport(), null);
    assert.deepEqual(copy(h.controller.getContext()), before);
    assert.equal(h.displayed(), "A");
    assert.deepEqual(h.applies, []);
    assert.equal(h.errors.at(-1).code, "RELINK_CASE_MISMATCH");
  }
});

test("explicit case selection after relink still applies the chosen DB case", async () => {
  const h = relinkHarness();
  await h.controller.open();
  await h.controller.openReport();
  await h.controller.selectCase("B");
  assert.deepEqual(h.applies, ["B"]);
  assert.equal(h.displayed(), "B");
  assert.equal(h.controller.getContext().references.database_path, "B.db");
});

test("relink with no saved reference ID fails instead of choosing another case", async () => {
  const h = relinkHarness({snapshot: () => ({reference_data: {}})});
  await h.controller.open();
  const before = copy(h.controller.getContext());
  assert.equal(await h.controller.openReport(), null);
  assert.deepEqual(copy(h.controller.getContext()), before);
  assert.deepEqual(h.applies, []);
  assert.equal(h.errors.at(-1).code, "RELINK_REFERENCE_MISSING");
});

test("native drops are ordered by start signals, not completion order", async () => {
  const h = harness();
  h.startReport("drop-A");
  h.startReport("drop-B");
  h.emitReport(report("B"), "drop-B");
  await tick();
  h.emitReport(report("A"), "drop-A");
  await tick();
  assert.deepEqual(h.applies, ["B"]);
  assert.equal(h.controller.getContext().references.report_path, "B.json");
});

test("an old native drop cannot replace a later manual report selection", async () => {
  const h = harness();
  h.startReport("drop-A");
  await h.controller.loadReport("B.json");
  h.emitReport(report("A"), "drop-A");
  await tick();
  assert.deepEqual(h.applies, ["B"]);
  assert.equal(h.displayed(), "B");
});

test("stale native errors are ignored and current native errors are displayed", async () => {
  const h = harness();
  h.startReport("drop-A");
  h.startReport("drop-B");
  h.emitReport(report("B"), "drop-B");
  await tick();
  h.emitReportError("drop-A", "OLD_DROP");
  assert.equal(h.errors.length, 0);
  h.startReport("drop-C");
  h.emitReportError("drop-C", "DROP_COUNT");
  assert.equal(h.errors.length, 1);
  assert.equal(h.errors[0].code, "DROP_COUNT");
  assert.equal(h.displayed(), "B");
});

test("a legacy bridge without a start signal still accepts a completed drop", async () => {
  const h = harness({noDropStarted: true});
  h.emitReport(report("B"), "legacy-drop");
  await tick();
  assert.equal(h.displayed(), "B");
});
