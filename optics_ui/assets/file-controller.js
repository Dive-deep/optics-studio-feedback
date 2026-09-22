/* Local file workflows. Views remain replaceable; no prediction/training/LLM calls. */
(function () {
  "use strict";
  const clone = value => JSON.parse(JSON.stringify(value));
  window.createOpticsFileController = function (hooks) {
    let context = {
      references: {report_path: null, database_path: null, target_path: null},
      report: null, target: null, cases: [], sessionPath: null,
      candidateData: null, candidateStatus: "idle", candidateError: null
    };
    let revision = 0;
    let targetRevision = 0;
    let candidateRevision = 0;
    const dropTickets = new Map();
    const hasDropStarted = typeof window.opticsBridge.onReportLoadStarted === "function";
    async function call(method, params = {}) {
      return window.opticsBridge.request(method, params);
    }
    function changed() { hooks.contextChanged(context); }
    async function refreshCandidateData() {
      const ticket = ++candidateRevision, owner = context;
      const databasePath = context.references.database_path;
      context.candidateData = null;
      context.candidateError = null;
      context.candidateStatus = databasePath ? "loading" : "unavailable";
      changed();
      if (!databasePath) return null;
      const current = () => ticket === candidateRevision && context === owner
        && context.references.database_path === databasePath;
      try {
        const result = await call("candidate_data", {path: databasePath});
        if (!current()) return null;
        if (!result || !Array.isArray(result.cases)) throw new Error("후보 데이터 형식이 올바르지 않습니다.");
        context.candidateData = result;
        context.candidateStatus = "ready";
        changed();
        return result;
      } catch (error) {
        if (!current()) return null;
        context.candidateStatus = "error";
        context.candidateError = {code: error.code || "CANDIDATE_DATA", message: error.message};
        changed();
        return null;
      }
    }
    function requestCandidateData() {
      // Views opt in to this read-only dataset; other file-controller users
      // need not load a full candidate pool.
      if (hooks.enableCandidates) void refreshCandidateData();
    }
    async function guarded(operation, isCurrent = () => true) {
      try { return await operation(); }
      catch (error) { if (isCurrent()) hooks.error(error); return null; }
    }
    function relinkIntent() {
      if (!context.sessionPath || !context.references.report_path || context.report) return null;
      return {referenceId: hooks.snapshot()?.reference_data?.id};
    }
    async function acceptReport(record, current, relink = null) {
      if (current !== revision || !record || record.status === "cancelled") return null;
      if (relink && (typeof relink.referenceId !== "string" || !relink.referenceId)) {
        throw Object.assign(new Error("복원된 Workspace의 참조 케이스 ID를 확인할 수 없습니다. 기존 설정은 유지됩니다."),
          {code: "RELINK_REFERENCE_MISSING"});
      }
      const listing = await call("list_cases", {path: record.database_path});
      if (current !== revision) return null;
      const cases = listing.cases || [];
      if (relink) {
        const existing = cases.find(item => item.id === relink.referenceId && item.ui_compatible === true);
        if (!existing) {
          throw Object.assign(new Error("선택한 DB에 복원된 참조 케이스 " + relink.referenceId +
            "가 없거나 현재 UI와 호환되지 않습니다. 기존 설정은 유지됩니다."), {code: "RELINK_CASE_MISMATCH"});
        }
        // Relink only the files: do not apply the DB prescription over the
        // edited optics, ranges, camera, or other restored session settings.
        context = {...context, report: record, cases, candidateData: null, candidateStatus: "idle", candidateError: null,
          references: {...context.references, report_path: record.report_path, database_path: record.database_path}};
        changed();
        requestCandidateData();
        hooks.notice("리포트 참조를 다시 연결했습니다. 복원된 설계 설정은 유지됩니다.");
        return record;
      }
      const compatible = cases.filter(item => item.ui_compatible !== false);
      const chosen = compatible.find(item => item.id === record.suggested_case_id)
        || compatible.find(item => item.status === "SUCCESS")
        || compatible[0];
      if (!chosen) throw Object.assign(new Error("현재 화면이 지원하는 광학계 케이스가 없습니다."), {code: "NO_COMPATIBLE_CASE"});
      const data = await call("load_case", {path: record.database_path, case_id: chosen.id});
      if (current !== revision) return null;
      // UI validation happens before committing the new file references.
      hooks.applyCase(data);
      context = {...context, report: record, cases, candidateData: null, candidateStatus: "idle", candidateError: null,
        references: {...context.references, report_path: record.report_path, database_path: record.database_path}};
      changed();
      requestCandidateData();
      hooks.notice("리포트와 DB를 불러왔습니다. 참조 케이스: " + chosen.id);
      return record;
    }
    function requestReport(method, params = {}) {
      // Own the operation before file parsing/native dialog completion, not
      // when the report happens to arrive.
      const current = ++revision;
      return guarded(async () => {
        const relink = relinkIntent();
        const record = await call(method, params);
        if (current !== revision) return null;
        return acceptReport(record, current, relink);
      }, () => current === revision);
    }
    function snapshot() {
      return {...hooks.snapshot(), target_snapshot: context.target ? clone(context.target.profile) : null};
    }
    const controller = {
      getContext: () => context,
      refreshCandidates: refreshCandidateData,
      openReport: () => requestReport("choose_report"),
      loadReport: path => requestReport("load_report", {path}),
      selectCase: (id, options = {}) => {
        const current = ++revision;
        const databasePath = context.references.database_path;
        return guarded(async () => {
          const data = await call("load_case", {path: databasePath, case_id: id});
          if (current !== revision || (options.isCurrent && !options.isCurrent())) return null;
          hooks.applyCase(data);
          hooks.notice("참조 케이스를 불러왔습니다: " + id);
          return data;
        }, () => current === revision);
      },
      openTarget: () => {
        const current = ++targetRevision;
        return guarded(async () => {
          const result = await call("choose_target");
          if (current !== targetRevision || !result || result.status === "cancelled") return null;
          context.target = result;
          context.references.target_path = result.path;
          changed();
          hooks.notice("목표 JSON을 읽기 전용으로 불러왔습니다.");
          return result;
        }, () => current === targetRevision);
      },
      save: () => guarded(async () => {
        const current = revision, savedContext = context;
        const result = await call("choose_session_save", {state: snapshot(), references: clone(context.references)});
        if (result?.status === "cancelled") return null;
        if (current === revision && context === savedContext) context.sessionPath = result.path;
        hooks.notice("Workspace 설정을 저장했습니다: " + result.path);
        return result;
      }),
      exportBundle: () => guarded(async () => {
        const result = await call("export_bundle", {state: snapshot(), references: clone(context.references)});
        if (result?.status === "cancelled") return null;
        hooks.notice("선택한 파일과 Workspace 설정을 ZIP으로 내보냈습니다: " + result.path);
        return result;
      }),
      open: () => {
        const current = ++revision;
        const targetAtStart = ++targetRevision;
        return guarded(async () => {
          const result = await call("choose_session_open");
          if (current !== revision || !result || result.status === "cancelled") return null;
          const restoredContext = {
            references: clone(result.references), report: null, cases: [], sessionPath: result.path,
            candidateData: null, candidateStatus: "idle", candidateError: null,
            target: result.state.target_snapshot ? {profile: clone(result.state.target_snapshot), read_only: true} : null
          };
          // A newer explicit target choice wins over the target saved in an
          // earlier session-open request; report/case and target have separate
          // ownership unless the workspace itself is replaced.
          if (targetAtStart !== targetRevision) {
            restoredContext.target = context.target;
            restoredContext.references.target_path = context.references.target_path;
          }
          // The hook validates the full UI snapshot before committing it.
          hooks.restore(result.state);
          context = restoredContext;
          changed();
          const isCurrent = () => current === revision && context === restoredContext;
          const warnings = result.warnings || [];
          const missing = key => warnings.some(item => item.code === "MISSING_REFERENCE" &&
            (item.reference_key === key || String(item.message || "").startsWith(key + " ")));
          const notices = warnings.map(item => item.message);
          if (restoredContext.references.report_path && !missing("report_path")) {
            try {
              const record = await call("load_report", {path: restoredContext.references.report_path});
              if (!isCurrent()) return null;
              restoredContext.report = record;
            } catch (error) {
              if (!isCurrent()) return null;
              notices.push(error.message);
            }
          }
          if (restoredContext.references.database_path && !missing("database_path")) {
            try {
              const listing = await call("list_cases", {path: restoredContext.references.database_path});
              if (!isCurrent()) return null;
              restoredContext.cases = listing.cases || [];
            } catch (error) {
              if (!isCurrent()) return null;
              notices.push(error.message);
            }
          }
          if (!isCurrent()) return null;
          changed();
          requestCandidateData();
          hooks.notice(notices.length ? "설정 복원 완료 · 파일 재연결 필요: " + notices.join(" / ") : "Workspace 설정과 화면을 복원했습니다.");
          return result;
        }, () => current === revision);
      },
      computeTest: target => call("compute_test", {target})
    };
    if (hasDropStarted) {
      window.opticsBridge.onReportLoadStarted(envelope => {
        if (!envelope || typeof envelope.id !== "string") return;
        const current = ++revision;
        dropTickets.clear();
        dropTickets.set(envelope.id, {current, relink: relinkIntent()});
      });
    }
    window.opticsBridge.onReportLoaded(envelope => {
      const operation = hasDropStarted ? dropTickets.get(envelope.id)
        : {current: ++revision, relink: relinkIntent()};
      if (hasDropStarted) dropTickets.delete(envelope.id);
      if (!operation || operation.current !== revision) return;
      const {current, relink} = operation;
      if (envelope.ok) {
        return guarded(() => acceptReport(envelope.data, current, relink), () => current === revision);
      }
      hooks.error(Object.assign(new Error(envelope.error?.message || "리포트 파일을 열 수 없습니다."), {code: envelope.error?.code}));
    });
    return controller;
  };
})();
