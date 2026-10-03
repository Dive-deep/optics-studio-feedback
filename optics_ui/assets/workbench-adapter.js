/* Native shell coordination only; never an optical or provider job transport. */
(function (root) {
  "use strict";
  const clone = value => value === undefined ? null : JSON.parse(JSON.stringify(value));
  const routes = new Set(["workspace", "update", "sim", "auto"]);
  const actions = new Set(["model", "open", "save", "export", "targets", "candidates", "configure"]);
  const chartKinds = new Set(["mtf", "spot"]);
  const initialCamera = {position:[67,34,63],target:[24,0,0],zoom:1,fov:34};
  function invalid(message) { throw new Error(message); }
  function canonical(value) {
    if (value === null || typeof value === "string" || typeof value === "boolean") return value;
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (Array.isArray(value)) return value.map(canonical);
    if (!value || typeof value !== "object") invalid("세션 설정은 유한한 JSON이어야 합니다.");
    const result = Object.create(null);
    Object.keys(value).sort().forEach(key => { result[key] = canonical(value[key]); });
    return result;
  }
  function initialPose(camera) {
    if (camera == null) return true;
    return ["position","target"].every(key => Array.isArray(camera[key]) && camera[key].length===3 &&
      camera[key].every((value,index) => Number.isFinite(value) && Math.abs(value-initialCamera[key][index])<1e-10)) &&
      Math.abs(camera.zoom-1)<1e-12 && Math.abs(camera.fov-34)<1e-12;
  }
  root.opticsSessionFingerprint = function (snapshot, references) {
    const semantic = {...snapshot};
    delete semantic.workbench;
    // The renderer initializes asynchronously. Its known default pose is the
    // same state as a not-yet-created camera; this never changes saved data.
    if (initialPose(semantic.camera)) semantic.camera = initialCamera;
    return JSON.stringify(canonical({snapshot:semantic,references}));
  };
  root.createOpticsWorkbenchAdapter = function (hooks) {
    let transport = null, pendingState = false;
    const api = {
      native: false,
      emitState() {
        if (api.native) notify("state", hooks.getState());
      },
      changed() {
        if (pendingState || !api.native) return;
        pendingState = true;
        queueMicrotask(() => { pendingState = false; api.emitState(); });
      },
      requestParameters() {
        if (!api.native) return false;
        notify("parameters_requested", hooks.getState().parameter_payload);
        return true;
      },
      toggleLlm() {
        if (!api.native) return false;
        notify("llm_toggle", {draft: hooks.getState().llm_draft});
        return true;
      },
      requestChart(kind) {
        if (!chartKinds.has(kind)) invalid("지원하지 않는 그래프입니다.");
        if (!api.native) return false;
        notify("chart_requested", {kind, data:hooks.getChartData(kind)});
        return true;
      },
      sessionRestored(workbench) {
        if (!api.native) return;
        notify("session_restored", {workbench: workbench || null});
        api.emitState();
      },
      async command(action, payload = {}) {
        if (!payload || typeof payload !== "object" || Array.isArray(payload)) invalid("작업대 요청 형식이 올바르지 않습니다.");
        let result;
        if (action === "get_state") return clone(hooks.getState());
        if (action === "get_session_snapshot") return clone(hooks.getSessionSnapshot());
        if (action === "get_chart_data") {
          if (!chartKinds.has(payload.kind)) invalid("지원하지 않는 그래프입니다.");
          return clone(hooks.getChartData(payload.kind));
        }
        if (action === "navigate") {
          if (!routes.has(payload.page)) invalid("지원하지 않는 작업 페이지입니다.");
          result = await hooks.actions[payload.page]();
        } else if (action === "apply_parameters") {
          const clean = root.OpticsWorkbenchContract.validateParameterUpdate(hooks.getState().parameter_payload, payload);
          result = await hooks.applyParameters(clean);
        } else if (action === "set_shell_state") {
          const clean = root.OpticsWorkbenchContract.validateShellState(payload);
          result = await hooks.setShellState(clean);
        } else if (action === "set_llm_draft") {
          if (typeof payload.draft !== "string" || payload.draft.length > 200000) invalid("LLM 초안은 200000자 이내의 문자열이어야 합니다.");
          result = await hooks.setLlmDraft(payload.draft);
        } else if (action === "set_chart_view") {
          if (!chartKinds.has(payload.kind)) invalid("지원하지 않는 그래프입니다.");
          if (payload.revision !== hooks.getChartData(payload.kind).revision) invalid("분석 결과가 변경되어 이전 그래프 보기를 적용할 수 없습니다.");
          const view = payload.view;
          if (!view || typeof view !== "object" || Array.isArray(view) || Object.keys(view).length!==3 ||
              Object.keys(view).some(key=>!["k","x","y"].includes(key)) ||
              ![view.k,view.x,view.y].every(Number.isFinite) || view.k<1 || view.k>12) invalid("그래프 확대·이동 값이 올바르지 않습니다.");
          result = await hooks.setChartView({kind:payload.kind,revision:payload.revision,view:{k:view.k,x:view.x,y:view.y}});
        } else if (actions.has(action)) {
          result = await hooks.actions[action]();
        } else {
          invalid("지원하지 않는 작업대 명령입니다.");
        }
        api.emitState();
        if (action === "open" && result?.status === "loaded") {
          notify("session_opened", {session_fingerprint:hooks.getSessionSnapshot().session_fingerprint});
        }
        return clone(result);
      }
    };
    function notify(type, payload) {
      if (transport) transport.notify(JSON.stringify({type, payload: clone(payload)}));
    }
    root.opticsWorkbench = api;
    api.ready = Promise.resolve(root.opticsBridge?.ready).then(ready => {
      const native = root.opticsBridge?.workbench;
      if (!ready || !native || typeof native.notify !== "function") return false;
      transport = native;
      api.native = true;
      hooks.setNativeMode?.(true);
      notify("ready", hooks.getState());
      api.emitState();
      return true;
    });
    return api;
  };
})(typeof window !== "undefined" ? window : globalThis);
