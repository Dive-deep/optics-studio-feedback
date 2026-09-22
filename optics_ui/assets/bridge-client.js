/* Desktop file/diagnostic bridge. No optical job or LLM execution transport. */
(function () {
  "use strict";
  const pending = new Map();
  const reportListeners = new Set();
  const reportStartListeners = new Set();
  let desktop = null;
  let sequence = 0;
  let readyResolve;
  const ready = new Promise(resolve => { readyResolve = resolve; });
  const api = {
    available: false,
    ready,
    onReportLoaded(listener) {
      reportListeners.add(listener);
      return () => reportListeners.delete(listener);
    },
    onReportLoadStarted(listener) {
      reportStartListeners.add(listener);
      return () => reportStartListeners.delete(listener);
    },
    async request(method, params = {}) {
      await ready;
      if (!desktop) throw Object.assign(new Error("데스크톱 앱에서 사용할 수 있는 기능입니다."), {code: "DESKTOP_UNAVAILABLE"});
      const id = "ui-" + (++sequence);
      return new Promise((resolve, reject) => {
        // Native dialogs can remain open while the user selects a path.
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(Object.assign(new Error("요청 응답 시간이 초과되었습니다."), {code: "REQUEST_TIMEOUT"}));
        }, method === "compute_test" ? 15000 : 300000);
        pending.set(id, {resolve, reject, timer});
        desktop.dispatch(JSON.stringify({id, method, params}), text => settle(text));
      });
    }
  };
  function decode(text) {
    return typeof text === "string" ? JSON.parse(text) : text;
  }
  function settle(text) {
    let envelope;
    try { envelope = decode(text); } catch (_) { return; }
    const item = pending.get(envelope.id);
    if (!item || (envelope.ok && envelope.data && envelope.data.deferred)) return;
    clearTimeout(item.timer);
    pending.delete(envelope.id);
    if (envelope.ok) item.resolve(envelope.data);
    else item.reject(Object.assign(new Error(envelope.error?.message || "요청 처리에 실패했습니다."), {code: envelope.error?.code || "DESKTOP_ERROR"}));
  }
  window.opticsBridge = api;
  if (!window.qt?.webChannelTransport || typeof QWebChannel !== "function") {
    readyResolve(false);
    return;
  }
  new QWebChannel(qt.webChannelTransport, channel => {
    desktop = channel.objects.desktop;
    if (!desktop) { readyResolve(false); return; }
    desktop.responseReady.connect(settle);
    desktop.reportLoadStarted?.connect(text => {
      let event;
      try { event = decode(text); } catch (_) { return; }
      for (const listener of reportStartListeners) listener(event);
    });
    desktop.reportLoaded.connect(text => {
      let envelope;
      try { envelope = decode(text); } catch (_) { return; }
      for (const listener of reportListeners) listener(envelope);
    });
    api.available = true;
    readyResolve(true);
    window.dispatchEvent(new Event("optics-desktop-ready"));
  });
})();
