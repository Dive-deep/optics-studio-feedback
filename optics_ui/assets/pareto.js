/* Stored-result evaluation only. No prediction, simulation, or implicit target profile. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.OpticsPareto = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const KEYS = ['mtf', 'spot', 'horizontal_fov'];
  const SCORE_POLICY = 'relative_target_margin_v1';
  // Dimensionless numerical tolerance, not the 5% engineering allowance.
  const EPS = 1e-12;
  const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
  const finite = x => typeof x === 'number' && Number.isFinite(x);
  const text = x => typeof x === 'string' && x.trim().length > 0;
  const flag = x => x === true || x === 1;
  const close = (a, b) => Math.abs(a - b) <= EPS * Math.max(1, Math.abs(a), Math.abs(b));
  const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const rowOrder = (a, b) => cmp(a.id || '', b.id || '') || a.input_index - b.input_index;
  const diagnostic = (code, message) => ({code, message});
  function conditionSignature(value, seen = new Set()) {
    if (value === null || typeof value === 'string' || typeof value === 'boolean' || finite(value)) return JSON.stringify(value);
    if ((!object(value) && !Array.isArray(value)) || seen.has(value)) throw new Error('Non-JSON condition');
    seen.add(value);
    const result = Array.isArray(value) ? '[' + value.map(item=>conditionSignature(item,seen)).join(',') + ']' :
      '{' + Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+conditionSignature(value[key],seen)).join(',') + '}';
    seen.delete(value);
    return result;
  }
  function exclude(row, reason) {
    row.evaluation = {...row.evaluation,status:'UNKNOWN',comparison_ready:false,
      reasons:[...new Set(row.evaluation.reasons.concat(reason))],mtf_quality:null,objectives:null,category_losses:null,score:null};
  }

  function validateProfile(profile) {
    const errors = [];
    const fail = (code, message) => errors.push(diagnostic(code, message));
    if (!object(profile) || profile.profile_version !== 1) {
      return {errors:[diagnostic('TARGET_SCHEMA', '지원하는 profile_version 1 목표 JSON이 필요합니다.')]};
    }
    const allowed = ['profile_id','profile_version','read_only','is_ui_example','category_weights',
      'relative_tolerance','conditions_policy','targets','notes'];
    if (Object.keys(profile).some(key => !allowed.includes(key))) fail('TARGET_FIELD', '지원하지 않는 목표 설정 필드가 있습니다.');
    const weights = profile.category_weights;
    if (!object(weights) || Object.keys(weights).some(key => !KEYS.includes(key)) ||
        KEYS.some(key => !finite(weights[key]) || weights[key] < 0) ||
        !(KEYS.reduce((sum, key) => sum + weights[key], 0) > 0)) {
      fail('TARGET_WEIGHTS', '세 범주의 유한한 0 이상 가중치와 양수 합계가 필요합니다.');
    }
    const tolerance = profile.relative_tolerance;
    if (!finite(tolerance) || tolerance < 0 || tolerance >= 1) fail('TARGET_TOLERANCE', '상대 예외 허용치는 0 이상 1 미만이어야 합니다.');
    const policy = profile.conditions_policy;
    if (!object(policy) || policy.prefer !== 'current_database_analysis_metadata' ||
        policy.fallback_does_not_recalculate_results !== true ||
        Object.keys(policy).some(key => !['prefer','display_defaults','fallback_does_not_recalculate_results'].includes(key))) {
      fail('TARGET_CONDITIONS', '현재 DB 분석 조건을 사용하는 명시적인 조건 정책이 필요합니다.');
    }
    const targets = profile.targets;
    if (!Array.isArray(targets) || !targets.length) return {errors:errors.concat(diagnostic('TARGET_VALUES', '목표 항목이 없습니다.'))};
    const groups = {mtf:[], spot:[], horizontal_fov:[]};
    const ids = new Set(), mtfConditions = new Set();
    for (const target of targets) {
      if (!object(target) || !text(target.id) || ids.has(target.id) || target.required !== true ||
          !KEYS.includes(target.category) || !finite(target.value) || target.value <= 0) {
        fail('TARGET_CRITERION', '누락·중복 또는 지원하지 않는 목표 항목이 있습니다.');
        continue;
      }
      ids.add(target.id);
      const common = ['id','category','metric','comparator','value','unit','required'];
      const extras = target.category === 'mtf' ? ['field_norm','orientation','frequency_lp_per_mm'] :
        target.category === 'spot' ? ['field_norm'] : [];
      if (Object.keys(target).some(key => !common.concat(extras).includes(key))) fail('TARGET_CRITERION_FIELD', '지원하지 않는 목표 조건 필드가 있습니다.');
      if (target.category === 'mtf') {
        if (target.metric !== 'mtf' || target.comparator !== '>=' || target.unit !== 'fraction' || target.value > 1 ||
            !finite(target.field_norm) || target.field_norm < 0 || !finite(target.frequency_lp_per_mm) || target.frequency_lp_per_mm <= 0 ||
            !['SAGITTAL','TANGENTIAL'].includes(target.orientation)) fail('TARGET_MTF', 'MTF 목표의 단위·조건·비교 연산자를 지원하지 않습니다.');
        const condition = [target.field_norm,target.orientation,target.frequency_lp_per_mm].join('|');
        if (mtfConditions.has(condition)) fail('TARGET_MTF_DUPLICATE', 'MTF 목표 조건이 중복되었습니다.');
        mtfConditions.add(condition);
      } else if (target.category === 'spot') {
        if (target.metric !== 'spot_rms_diameter' || target.comparator !== 'close_to' || target.unit !== 'um' || target.field_norm !== 1) {
          fail('TARGET_SPOT', 'Spot은 1.0F RMS 직경(μm)의 목표 근접 조건만 지원합니다.');
        }
      } else if (target.metric !== 'horizontal_fov_full' || target.comparator !== 'close_to' || target.unit !== 'deg') {
        fail('TARGET_FOV', 'Horizontal FOV는 전체 각도(deg)의 목표 근접 조건만 지원합니다.');
      }
      groups[target.category].push(target);
    }
    if (!groups.mtf.length || groups.spot.length !== 1 || groups.horizontal_fov.length !== 1) fail('TARGET_GROUPS', 'MTF 및 단일 Spot·Horizontal FOV 목표가 모두 필요합니다.');
    return {errors, weights, tolerance, groups};
  }

  function axisInfo(key) {
    const labels = {mtf:'MTF · 1 − worst target ratio',spot:'Spot · relative distance to target',horizontal_fov:'Horizontal FOV · relative distance to target'};
    return KEYS.includes(key) ? {key,label:labels[key],unit:'dimensionless',direction:'minimize'} : null;
  }
  function objectivePoint(row, dimensions = ['spot','horizontal_fov']) {
    const objectives = row?.evaluation?.objectives;
    return objectives && Array.isArray(dimensions) && dimensions.length === 2 && dimensions.every(key => finite(objectives[key])) ?
      {id:row.id,x:objectives[dimensions[0]],y:objectives[dimensions[1]],input_index:row.input_index} : null;
  }
  function evaluateRow(raw, inputIndex, contract) {
    const row = object(raw) ? raw : {};
    const reasons = Array.isArray(row.exclusion_reasons) ? row.exclusion_reasons.map(reason => typeof reason === 'string' ? reason : reason?.code || 'SOURCE_EXCLUSION') : [];
    if (!text(row.id)) reasons.push('MISSING_CASE_ID');
    if (!flag(row.ui_compatible)) reasons.push('INCOMPATIBLE_UI');
    if (!flag(row.geometry_valid)) reasons.push('INVALID_GEOMETRY');
    if (!flag(row.trace_success)) reasons.push('TRACE_UNAVAILABLE');
    if (row.comparison_ready !== true) reasons.push('COMPARISON_NOT_READY');
    if (!text(row.cohort_key) || !text(row.source_kind)) reasons.push('MISSING_COHORT');
    const conditions = row.conditions;
    if (!object(conditions) || !finite(row.temperature_c) || !finite(conditions.temperature_c) ||
        !close(row.temperature_c, conditions.temperature_c) ||
        !['analysis_metadata','database_results'].includes(conditions.temperature_source) ||
        !object(conditions.outputs) || ['first_order','mtf','spot'].some(key =>
          !object(conditions.outputs[key]) || !Object.keys(conditions.outputs[key]).length)) reasons.push('MISSING_ANALYSIS_CONDITIONS');
    const spot = row.metrics?.spot_rms_diameter_um, fov = row.metrics?.horizontal_fov_deg;
    if (!finite(spot) || spot < 0 || !finite(fov) || fov < 0) reasons.push('MISSING_OR_INVALID_METRIC');
    const ratios = [], checks = [];
    for (const target of contract.groups.mtf) {
      const matches = Array.isArray(row.mtf) ? row.mtf.filter(point => object(point) &&
        finite(point.field_norm) && close(point.field_norm,target.field_norm) && point.orientation === target.orientation &&
        finite(point.frequency_lp_per_mm) && close(point.frequency_lp_per_mm,target.frequency_lp_per_mm)) : [];
      if (matches.length !== 1 || !finite(matches[0].mtf) || matches[0].mtf < 0 || matches[0].mtf > 1) {
        reasons.push(matches.length > 1 ? 'AMBIGUOUS_MTF_CRITERION' : 'MISSING_OR_INVALID_MTF');
        continue;
      }
      const ratio = matches[0].mtf / target.value;
      if (!finite(ratio)) reasons.push('NONFINITE_DERIVED_VALUE');
      ratios.push(ratio);
      checks.push({target_id:target.id,category:'mtf',actual:matches[0].mtf,target:target.value,
        pass:ratio >= 1 - EPS,near:ratio >= 1 - contract.tolerance - EPS});
    }
    for (const [category, actual] of [['spot',spot],['horizontal_fov',fov]]) {
      const target = contract.groups[category][0];
      if (finite(actual) && actual >= 0) {
        const distance = Math.abs(actual - target.value) / target.value;
        if (!finite(distance)) reasons.push('NONFINITE_DERIVED_VALUE');
        checks.push({target_id:target.id,category,actual,target:target.value,
          pass:distance <= EPS,near:distance <= contract.tolerance + EPS});
      }
    }
    let evaluation = {status:'UNKNOWN',comparison_ready:false,reasons:[...new Set(reasons)],criteria:checks,
      mtf_quality:null,objectives:null,category_losses:null,score:null,score_policy:SCORE_POLICY};
    if (!reasons.length) {
      const quality = Math.min(...ratios);
      const objectives = {mtf:1-quality,spot:Math.abs(spot-contract.groups.spot[0].value)/contract.groups.spot[0].value,
        horizontal_fov:Math.abs(fov-contract.groups.horizontal_fov[0].value)/contract.groups.horizontal_fov[0].value};
      const weightScale = Math.max(...KEYS.map(key=>contract.weights[key]));
      const weightTotal = KEYS.reduce((sum,key)=>sum+contract.weights[key]/weightScale,0);
      const score = KEYS.reduce((sum,key) => sum + objectives[key]*(contract.weights[key]/weightScale/weightTotal),0);
      evaluation = {...evaluation,status:checks.every(c=>c.pass)?'PASS':checks.every(c=>c.near)?'NEAR_PASS':'NG',
        comparison_ready:true,mtf_quality:quality,objectives,category_losses:{...objectives},score};
    }
    return {...row,input_index:inputIndex,evaluation};
  }

  function evaluateCases(cases, profile) {
    const contract = validateProfile(profile);
    if (contract.errors.length) return {status:'unsupported_profile',errors:contract.errors,rows:[],cohorts:[],score_policy:SCORE_POLICY};
    if (!Array.isArray(cases)) return {status:'invalid_data',errors:[diagnostic('CASES_TYPE','케이스 배열이 필요합니다.')],rows:[],cohorts:[],score_policy:SCORE_POLICY};
    const rows = cases.map((row,i)=>evaluateRow(row,i,contract)).sort(rowOrder);
    // A declared cohort cannot override contradictory condition metadata.
    // The service owns semantic canonicalization; this verifies consistency.
    const signatures = new Map();
    for (const row of rows) {
      if (!row.evaluation.comparison_ready) continue;
      try {
        const key = JSON.stringify([row.cohort_key,row.source_kind]);
        if (!signatures.has(key)) signatures.set(key,{signatures:new Set(),rows:[]});
        const group = signatures.get(key);
        group.signatures.add(conditionSignature(row.conditions));group.rows.push(row);
      } catch (_) { exclude(row,'INVALID_ANALYSIS_CONDITIONS'); }
    }
    for (const group of signatures.values()) {
      if (group.signatures.size > 1) group.rows.forEach(row=>exclude(row,'COHORT_CONDITIONS_CONFLICT'));
    }
    // Case IDs drive UI selection. Identical duplicates are retained, while
    // contradictory records with one ID cannot identify a selectable design.
    const identities = new Map();
    for (const row of rows) {
      if (!text(row.id) || !text(row.cohort_key) || !text(row.source_kind)) continue;
      const key = JSON.stringify([row.cohort_key,row.source_kind,row.id]);
      if (!identities.has(key)) identities.set(key,[]);
      identities.get(key).push(row);
    }
    for (const duplicates of identities.values()) {
      if (duplicates.length < 2) continue;
      try {
        const records = duplicates.map(row => conditionSignature(Object.fromEntries(
          Object.entries(row).filter(([key])=>key!=='evaluation'&&key!=='input_index'))));
        if (new Set(records).size > 1) duplicates.forEach(row=>exclude(row,'CONFLICTING_CASE_ID'));
      } catch (_) { duplicates.forEach(row=>exclude(row,'CONFLICTING_CASE_ID')); }
    }
    const groups = new Map();
    for (const row of rows) {
      if (!row.evaluation.comparison_ready) continue;
      const key = JSON.stringify([row.cohort_key,row.source_kind]);
      if (!groups.has(key)) groups.set(key,{cohort_key:row.cohort_key,source_kind:row.source_kind,count:0,eligible_count:0});
      const group = groups.get(key); group.count++;
      if (['PASS','NEAR_PASS'].includes(row.evaluation.status)) group.eligible_count++;
    }
    return {status:'ready',errors:[],rows,cohorts:[...groups.values()].sort((a,b)=>cmp(a.cohort_key,b.cohort_key)||cmp(a.source_kind,b.source_kind)),
      score_policy:SCORE_POLICY,profile_id:profile.profile_id??null,profile_version:profile.profile_version,
      category_weights:{...contract.weights},relative_tolerance:contract.tolerance};
  }

  function nonDominated(rows, keys) {
    // Conservative numerical dominance: no raw coordinate may worsen, and at
    // least one must improve by more than EPS. Near-identical objective vectors
    // remain together; unlike allowing EPS-sized worsening, this cannot create
    // tolerance-induced dominance cycles across three objectives.
    return rows.filter(candidate => !rows.some(other => other !== candidate &&
      keys.every(key=>other.evaluation.objectives[key] <= candidate.evaluation.objectives[key]) &&
      keys.some(key=>other.evaluation.objectives[key] < candidate.evaluation.objectives[key] - EPS)));
  }
  function explore(evaluated, options = {}) {
    const empty = {status:'ready',errors:[],rows:[],pareto_ids:[],full_pareto_ids:[],best_id:null,
      counts:{total:0,in_cohort:0,comparable:0,pass:0,near_pass:0,ng:0,unknown:0,shown:0,excluded:0},
      line_points:[],axes:[],score_policy:SCORE_POLICY};
    if (!evaluated || evaluated.status !== 'ready' || !Array.isArray(evaluated.rows)) return {...empty,status:evaluated?.status||'invalid_data',errors:evaluated?.errors||[]};
    const all = evaluated.rows;
    if (!object(options)) return {...empty,status:'invalid_options',errors:[diagnostic('EXPLORATION_OPTIONS','표시 옵션 객체가 필요합니다.')]};
    const mode = options.mode ?? 'eligible', dimensions = options.dimensions ?? ['spot','horizontal_fov'], projection = options.projection ?? 'pair';
    empty.counts.total = all.length;
    if (!['eligible','exploratory'].includes(mode) || !['pair','full'].includes(projection) || !Array.isArray(dimensions) ||
        dimensions.length !== 2 || new Set(dimensions).size !== 2 || dimensions.some(key=>!KEYS.includes(key))) {
      return {...empty,status:'invalid_options',errors:[diagnostic('EXPLORATION_OPTIONS','표시 모드 또는 성능 축을 지원하지 않습니다.')]};
    }
    empty.axes = dimensions.map(axisInfo);
    if (!text(options.cohort_key)) return {...empty,status:'cohort_required',errors:[diagnostic('COHORT_REQUIRED','비교할 분석 조건을 선택하세요.')]};
    const conditionRows = all.filter(row=>row.cohort_key===options.cohort_key);
    const kinds = [...new Set(conditionRows.filter(row=>row.evaluation.comparison_ready).map(row=>row.source_kind))];
    if (options.source_kind === undefined && kinds.length > 1) return {...empty,status:'source_required',errors:[diagnostic('SOURCE_REQUIRED','비교할 결과 출처를 선택하세요.')]};
    if (options.source_kind !== undefined && !text(options.source_kind)) return {...empty,status:'invalid_options',errors:[diagnostic('SOURCE_REQUIRED','유효한 결과 출처가 필요합니다.')]};
    const sourceKind = options.source_kind ?? kinds[0] ?? null;
    const cohort = conditionRows.filter(row=>sourceKind === null || row.source_kind===sourceKind);
    const valid = cohort.filter(row=>row.evaluation.comparison_ready);
    const rows = valid.filter(row=>mode==='exploratory'||['PASS','NEAR_PASS'].includes(row.evaluation.status)).slice().sort(rowOrder);
    const full = nonDominated(rows,KEYS), pair = nonDominated(rows,dimensions), front = projection==='full'?full:pair;
    // Exploratory visibility never promotes NG to the eligible recommendation.
    const eligibleFull = nonDominated(valid.filter(row=>['PASS','NEAR_PASS'].includes(row.evaluation.status)),KEYS);
    const minimumScore = eligibleFull.reduce((minimum,row)=>Math.min(minimum,row.evaluation.score),Infinity);
    // Compare to one minimum rather than a non-transitive epsilon sort comparator.
    const best = eligibleFull.filter(row=>row.evaluation.score <= minimumScore + EPS).sort(rowOrder)[0] || null;
    const line = projection==='full'?[]:pair.map(row=>objectivePoint(row,dimensions)).sort((a,b)=>a.x-b.x||a.y-b.y||cmp(a.id,b.id)||a.input_index-b.input_index);
    const counts = {total:all.length,in_cohort:cohort.length,comparable:valid.length,
      pass:cohort.filter(r=>r.evaluation.status==='PASS').length,near_pass:cohort.filter(r=>r.evaluation.status==='NEAR_PASS').length,
      ng:cohort.filter(r=>r.evaluation.status==='NG').length,unknown:cohort.filter(r=>r.evaluation.status==='UNKNOWN').length,
      shown:rows.length,excluded:all.length-rows.length};
    return {...empty,status:'ready',rows,pareto_ids:front.map(r=>r.id),full_pareto_ids:full.map(r=>r.id),best_id:best?.id??null,
      counts,line_points:line,cohort_key:options.cohort_key,source_kind:sourceKind,mode,dimensions:[...dimensions],projection};
  }
  return Object.freeze({evaluateCases,explore,axisInfo,objectivePoint,score_policy:SCORE_POLICY,numeric_tolerance:EPS});
});
