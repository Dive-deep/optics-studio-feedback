/* Pure boundaries for native parameter edits and desktop shell snapshots. */
(function (root) {
  "use strict";
  const reserved = new Set(["__proto__", "constructor", "prototype"]);
  const surfaceTypes = new Set(["STANDARD", "EVEN_ASPHERE"]);
  const pages = new Set(["workspace", "explorer", "tailoring", "update", "sim", "auto"]);
  function fail(message, code = "WORKBENCH_VALIDATION") {
    const error = new Error(message);
    error.code = code;
    throw error;
  }
  function record(value, label) {
    if (!value || typeof value !== "object" || Array.isArray(value)) fail(label + " 형식이 올바르지 않습니다.");
    return value;
  }
  function text(value, label) {
    if (typeof value !== "string") fail(label + "은 문자열이어야 합니다.");
    return value;
  }
  function bool(value, label) {
    if (typeof value !== "boolean") fail(label + "은 boolean이어야 합니다.");
    return value;
  }
  function number(value, label) {
    if (typeof value !== "number" || !Number.isFinite(value)) fail(label + "은 유한한 숫자여야 합니다.");
    return value;
  }
  function exactKeys(value, keys, label) {
    const actual = Object.keys(record(value, label));
    if (actual.length !== keys.length || actual.some(key => !keys.includes(key))) fail(label + " 항목이 올바르지 않습니다.");
  }
  function jsonCopy(value, depth = 0, ancestors = new Set()) {
    if (depth > 64) fail("설정 중첩이 너무 깊습니다.");
    if (value === null || typeof value === "string" || typeof value === "boolean") return value;
    if (typeof value === "number") return number(value, "설정값");
    if (typeof value !== "object" || ancestors.has(value)) fail("설정은 순환 참조가 없는 JSON이어야 합니다.");
    ancestors.add(value);
    let result;
    if (Array.isArray(value)) {
      const keys = Object.keys(value);
      if (keys.length !== value.length || Reflect.ownKeys(value).length !== value.length + 1 ||
          keys.some((key, index) => key !== String(index))) fail("목록 형식이 올바르지 않습니다.");
      result = value.map(item => jsonCopy(item, depth + 1, ancestors));
    } else {
      const proto = Object.getPrototypeOf(value);
      if (proto !== null && Object.getPrototypeOf(proto) !== null) fail("설정은 일반 JSON 객체여야 합니다.");
      const keys = Object.keys(value);
      if (Reflect.ownKeys(value).length !== keys.length || keys.some(key => reserved.has(key))) fail("예약된 설정 키는 사용할 수 없습니다.");
      result = {};
      for (const key of keys) {
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (!Object.hasOwn(descriptor, "value")) fail("설정에 접근자 속성을 사용할 수 없습니다.");
        result[key] = jsonCopy(descriptor.value, depth + 1, ancestors);
      }
    }
    ancestors.delete(value);
    return result;
  }
  function indexed(items, label, key, validate) {
    if (!Array.isArray(items)) fail(label + " 목록이 필요합니다.");
    const result = new Map();
    items.forEach(item => {
      record(item, label);
      validate(item);
      if (result.has(item[key])) fail(label + " ID가 중복되었습니다.");
      result.set(item[key], item);
    });
    return result;
  }
  function parameterSchema(payload) {
    record(payload, "파라미터 요청");
    text(payload.revision, "Revision");
    if (!Array.isArray(payload.materials) || payload.materials.some(item => typeof item !== "string" || !item) ||
        new Set(payload.materials).size !== payload.materials.length) fail("재질 목록이 올바르지 않습니다.");
    const lenses = indexed(payload.lenses, "렌즈", "index", lens => {
      if (!Number.isInteger(lens.index) || lens.index < 0 || !surfaceTypes.has(lens.surface_type) ||
          !payload.materials.includes(lens.material)) fail("렌즈 번호·재질·면 종류가 올바르지 않습니다.");
    });
    const parameters = indexed(payload.parameters, "파라미터", "id", p => {
      if (!text(p.id, "파라미터 ID") || reserved.has(p.id)) fail("파라미터 ID가 올바르지 않습니다.");
      for (const key of ["label", "group", "unit"]) text(p[key], "파라미터 " + key);
      if (p.kind !== "number") fail("지원하지 않는 파라미터 종류입니다.");
      bool(p.active, "활성 상태"); bool(p.available, "사용 가능 상태");
      if (Object.hasOwn(p, "coefficient")) bool(p.coefficient, "면 계수 표시");
      if (Object.hasOwn(p, "lens_index") && (!Number.isInteger(p.lens_index) || !lenses.has(p.lens_index))) fail("파라미터의 렌즈 번호가 올바르지 않습니다.");
      if (p.coefficient && !Object.hasOwn(p, "lens_index")) fail("면 계수의 렌즈 번호가 필요합니다.");
      if (!["min", "max", "value"].every(key => Object.hasOwn(p, key))) fail("범위와 현재값이 필요합니다.");
    });
    return {lenses, parameters};
  }
  function validateParameterUpdate(currentPayload, request) {
    const baseline = jsonCopy(currentPayload), candidate = jsonCopy(request);
    const base = parameterSchema(baseline), next = parameterSchema(candidate);
    if (candidate.revision !== baseline.revision) fail("설계 revision이 변경되어 이전 파라미터 편집을 적용할 수 없습니다.", "STALE_REVISION");
    if (JSON.stringify(candidate.materials) !== JSON.stringify(baseline.materials)) fail("재질 선택 목록을 변경할 수 없습니다.");
    if (base.lenses.size !== next.lenses.size || [...base.lenses.keys()].some(id => !next.lenses.has(id))) fail("광학계 렌즈 구성이 변경되었습니다.");
    if (base.parameters.size !== next.parameters.size || [...base.parameters.keys()].some(id => !next.parameters.has(id))) fail("파라미터 목록이 현재 설계와 다릅니다.");
    const lenses = baseline.lenses.map(lens => {
      const edited = next.lenses.get(lens.index);
      return {...lens, material: edited.material, surface_type: edited.surface_type};
    });
    const parameters = baseline.parameters.map(p => {
      const edited = next.parameters.get(p.id);
      for (const key of ["label", "group", "unit", "kind", "lens_index", "coefficient"]) {
        if (edited[key] !== p[key]) fail("파라미터 정의를 변경할 수 없습니다: " + p.id);
      }
      if (p.value === null) {
        if (p.min !== null || p.max !== null || p.active || edited.value !== null ||
            edited.min !== null || edited.max !== null || edited.active) fail("미제공 파라미터는 공란으로 유지해야 합니다: " + p.id);
        return {...p, min: null, max: null, value: null, active: false, available: false};
      }
      for (const key of ["min", "max", "value"]) number(p[key], p.id + " 기준 " + key);
      if (p.min >= p.max || p.value < p.min || p.value > p.max) fail("현재 설계의 기준 범위가 올바르지 않습니다: " + p.id);
      const min = number(edited.min, p.id + " Min"), max = number(edited.max, p.id + " Max");
      const requestedValue = number(edited.value, p.id + " Current");
      if (min >= max) fail("Min은 Max보다 작아야 합니다: " + p.id);
      const numericChanged = min !== p.min || max !== p.max || requestedValue !== p.value;
      const value = numericChanged ? Math.max(min, Math.min(max, requestedValue)) : p.value;
      const available = !p.coefficient || next.lenses.get(p.lens_index).surface_type === "EVEN_ASPHERE";
      return {...p, min, max, value, active: edited.active, available};
    });
    return {...baseline, revision: baseline.revision, parameters, lenses};
  }
  function relativeFile(value) {
    text(value, "소스 파일 경로");
    if (!value || value.includes("\0") || value.includes("\\") || value.includes(":") ||
        value.startsWith("/") || value.split("/").some(part => !part || part === "." || part === "..")) {
      fail("소스 파일은 작업 폴더 안의 상대 POSIX 경로여야 합니다.");
    }
    return value;
  }
  function sensitivityPanel(value) {
    if (value === null) return null;
    const panel = record(value, "Sensitivity");
    if (panel.format !== "optics-sensitivity-panel" || panel.schema_version !== 1 ||
        !["S1", "ST"].includes(panel.metric) || !Object.hasOwn(panel, "report")) fail("Sensitivity 패널 형식이 올바르지 않습니다.");
    for (const key of ["output_id", "report_path"]) {
      if (panel[key] !== null && panel[key] !== undefined) text(panel[key], "Sensitivity " + key);
    }
    if (Object.hasOwn(panel, "stale")) bool(panel.stale, "Sensitivity stale");
    if (panel.report !== null) record(panel.report, "Sobol 보고서");
    // Scientific report validation belongs to the native sensitivity service.
    // A JSON object passing here is not evidence of a valid Sobol analysis.
    return panel;
  }
  function splitterSizes(value, label) {
    if (!Array.isArray(value) || value.length !== 2 || value.some(size => !Number.isInteger(size) || size < 0 || size > 2147483647) ||
        value[0] + value[1] <= 0) fail(label + " 분할 크기가 올바르지 않습니다.");
  }
  function windowGeometry(value, label) {
    if (value === null) return;
    exactKeys(value, ["x", "y", "width", "height", "maximized"], label);
    for (const key of ["x", "y"]) {
      if (!Number.isInteger(value[key]) || value[key] < -2147483648 || value[key] > 2147483647) fail(label + " 위치가 올바르지 않습니다.");
    }
    for (const key of ["width", "height"]) {
      if (!Number.isInteger(value[key]) || value[key] < 1 || value[key] > 16777215) fail(label + " 크기가 올바르지 않습니다.");
    }
    bool(value.maximized, label + " 최대화");
  }
  function nativeLayout(value) {
    exactKeys(value, ["window", "llm_width", "explorer_split", "charts"], "레이아웃");
    windowGeometry(value.window, "작업대 창");
    if (!Number.isInteger(value.llm_width) || value.llm_width < 1 || value.llm_width > 16777215) fail("LLM 패널 폭이 올바르지 않습니다.");
    splitterSizes(value.explorer_split, "Explorer");
    exactKeys(value.charts, ["mtf", "spot"], "분석 창");
    for (const name of ["mtf", "spot"]) {
      const chart = value.charts[name];
      exactKeys(chart, ["open", "window"], name + " 분석 창");
      bool(chart.open, name + " 창 표시");
      windowGeometry(chart.window, name + " 분석 창");
    }
  }
  function validateShellState(value) {
    const state = jsonCopy(value);
    record(state, "작업대");
    if (![1, 2].includes(state.version) || !pages.has(state.page)) fail("작업대 버전 또는 페이지가 올바르지 않습니다.");
    const keys = ["version", "page", "llm_visible", "analysis_visible", "workspace_split", "explorer", "sensitivity"];
    if (state.version === 2) keys.push("layout");
    exactKeys(state, keys, "작업대");
    bool(state.llm_visible, "LLM 패널"); bool(state.analysis_visible, "분석 패널");
    splitterSizes(state.workspace_split, "작업대");
    if (state.version === 2) nativeLayout(state.layout);
    const explorer = state.explorer;
    exactKeys(explorer, ["workspace_root", "files", "current_file", "wrap_lines"], "소스 탐색기");
    const workspaceRoot = text(explorer.workspace_root, "작업 폴더");
    if (workspaceRoot.includes("\0") || !(/^(\/|[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+)/).test(workspaceRoot)) fail("작업 폴더는 절대 경로여야 합니다.");
    if (!Array.isArray(explorer.files) || explorer.files.length > 64 || new Set(explorer.files).size !== explorer.files.length) fail("소스 탭은 중복 없이 최대 64개까지 저장할 수 있습니다.");
    explorer.files.forEach(relativeFile);
    if (explorer.current_file !== null && !explorer.files.includes(explorer.current_file)) fail("현재 소스 탭이 열린 파일 목록에 없습니다.");
    bool(explorer.wrap_lines, "줄바꿈");
    state.sensitivity = sensitivityPanel(state.sensitivity);
    if (state.page === "sim") state.page = "workspace";
    return state;
  }
  root.OpticsWorkbenchContract = Object.freeze({validateParameterUpdate, validateShellState});
})(typeof window !== "undefined" ? window : globalThis);
