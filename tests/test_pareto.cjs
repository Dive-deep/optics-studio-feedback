const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Pareto = require('../design/pareto.js');
const profile = JSON.parse(fs.readFileSync(path.join(__dirname, '../examples/local-demo/target.json'), 'utf8'));
const copy = value => structuredClone(value);
function sample(id, {quality = 1, spot = 1.6, fov = 24, ...rest} = {}) {
  return {id, source_kind:'synthetic', origin:'SYNTHETIC_MATH_PROXY', ui_compatible:true,
    geometry_valid:true, trace_success:true, temperature_c:20,
    conditions:{temperature_c:20, temperature_source:'database_results', outputs:{
      first_order:{wavelength_nm:546.074},mtf:{wavelengths_nm:[546.074]},spot:{wavelengths_nm:[546.074]}}}, cohort_key:'20C-spectrum-v1',
    comparison_ready:true, exclusion_reasons:[], metrics:{spot_rms_diameter_um:spot, horizontal_fov_deg:fov},
    mtf:profile.targets.filter(t => t.category==='mtf').map(t => ({field_norm:t.field_norm,
      orientation:t.orientation, frequency_lp_per_mm:t.frequency_lp_per_mm, mtf:t.value*quality})), ...rest};
}
function evaluate(rows, p = profile) {return Pareto.evaluateCases(rows, p);}
function explore(rows, options = {}, p = profile) {
  return Pareto.explore(evaluate(rows, p), {cohort_key:'20C-spectrum-v1', mode:'eligible', ...options});
}
function deepFreeze(x) { if (x && typeof x==='object') {Object.freeze(x); Object.values(x).forEach(deepFreeze);} return x; }

test('exact target is PASS and all objectives and score are zero', () => {
  const result = evaluate([sample('a')]);
  assert.equal(result.status,'ready'); assert.equal(result.score_policy,'relative_target_margin_v1');
  assert.equal(result.rows[0].evaluation.status,'PASS');
  assert.deepEqual(result.rows[0].evaluation.objectives,{mtf:0,spot:0,horizontal_fov:0});
  assert.equal(result.rows[0].evaluation.score,0);
});
test('MTF surplus remains preferred beyond threshold and allows negative score', () => {
  const result = explore([sample('a'), sample('b',{quality:1.2})]);
  assert.equal(result.best_id,'b'); assert.deepEqual(result.full_pareto_ids,['b']);
  assert.ok(result.rows.find(r=>r.id==='b').evaluation.score<0);
});
test('worst normalized MTF margin is one category, not four independent weights', () => {
  const s=sample('a',{quality:.8,spot:1.92,fov:28.8});
  s.mtf[0].mtf=.4; s.mtf[1].mtf=.4; s.mtf[2].mtf=.3;
  const ev=evaluate([s]).rows[0].evaluation;
  assert.ok(Math.abs(ev.mtf_quality-.8)<1e-12);
  assert.ok(Math.abs(ev.score-.2)<1e-12);
});
test('target distance prefers both directions toward target rather than smaller raw value', () => {
  const rows=[sample('near',{spot:1.6,fov:24}),sample('smaller',{spot:1.2,fov:20}),sample('larger',{spot:2,fov:28})];
  const result=explore(rows,{mode:'exploratory'});
  assert.deepEqual(result.pareto_ids,['near']); assert.deepEqual(result.full_pareto_ids,['near']);
});
test('relative five-percent inclusive boundaries are NEAR_PASS despite binary rounding', () => {
  const row=sample('edge',{quality:.95,spot:1.68,fov:25.2});
  assert.equal(evaluate([row]).rows[0].evaluation.status,'NEAR_PASS');
  assert.equal(evaluate([sample('other',{spot:1.52,fov:22.8})]).rows[0].evaluation.status,'NEAR_PASS');
  assert.equal(evaluate([sample('outside',{spot:1.68001})]).rows[0].evaluation.status,'NG');
});
test('MTF 40 percent permits 38 but rejects a material amount below it', () => {
  const a=sample('a');a.mtf[0].mtf=.38;
  const b=copy(a);b.id='b';b.mtf[0].mtf=.37999;
  assert.equal(evaluate([a]).rows[0].evaluation.status,'NEAR_PASS');
  assert.equal(evaluate([b]).rows[0].evaluation.status,'NG');
});
test('eligible filters NG before score and exploratory includes valid NG', () => {
  const rows=[sample('pass'),sample('ng',{quality:2,spot:1.7})];
  const a=explore(rows);assert.deepEqual(a.rows.map(r=>r.id),['pass']);assert.equal(a.best_id,'pass');
  assert.equal(explore(rows,{mode:'exploratory'}).rows.length,2);
});
test('missing values are UNKNOWN and never become zeros or exploratory points', () => {
  for(const value of [null,undefined,NaN,Infinity]) {
    const row=sample('a');row.metrics.spot_rms_diameter_um=value;
    assert.equal(evaluate([row]).rows[0].evaluation.status,'UNKNOWN');
    assert.equal(explore([row],{mode:'exploratory'}).rows.length,0);
  }
});
test('zero physical result is not missing but MTF is zero and spot remains target distance one', () => {
  const ev=evaluate([sample('zero',{quality:0,spot:0,fov:0})]).rows[0].evaluation;
  assert.equal(ev.status,'NG');assert.deepEqual(ev.objectives,{mtf:1,spot:1,horizontal_fov:1});
});
test('negative metrics and MTF outside fraction range are UNKNOWN', () => {
  const a=sample('a',{spot:-1});const b=sample('b');b.mtf[0].mtf=1.1;
  assert.ok(evaluate([a,b]).rows.every(r=>r.evaluation.status==='UNKNOWN'));
});
test('geometry, trace, compatibility, and comparison metadata are mandatory', () => {
  const variants=[{geometry_valid:false},{trace_success:0},{ui_compatible:false},{comparison_ready:false},
    {cohort_key:null},{source_kind:''},{conditions:{}},{temperature_c:null},
    {conditions:{temperature_c:20,temperature_source:'display_default',outputs:{first_order:{x:1},mtf:{x:1},spot:{x:1}}}}];
  for(const patch of variants) assert.equal(explore([sample('x',patch)],{mode:'exploratory'}).rows.length,0);
});
test('numeric SQLite validity flags are accepted', () => {
  assert.equal(evaluate([sample('x',{geometry_valid:1,trace_success:1})]).rows[0].evaluation.status,'PASS');
});
test('missing one MTF criterion and ambiguous duplicate criterion are UNKNOWN', () => {
  const a=sample('a');a.mtf.pop();const b=sample('b');b.mtf.push(copy(b.mtf[0]));
  assert.ok(evaluate([a,b]).rows.every(r=>r.evaluation.status==='UNKNOWN'));
});
test('same objective ties retain all distinct designs in deterministic ID order', () => {
  const result=explore([sample('b'),sample('a'),sample('a')]);
  assert.deepEqual(result.rows.map(r=>r.id),['a','a','b']);
  assert.equal(result.pareto_ids.length,3);assert.equal(result.best_id,'a');
});
test('2D front differs from full 3D projected set; projected set never has line', () => {
  const rows=[sample('a',{quality:1,spot:1.6,fov:24}),sample('b',{quality:1.2,spot:1.632,fov:24.48})];
  const pair=explore(rows);assert.deepEqual(pair.pareto_ids,['a']);assert.deepEqual(pair.full_pareto_ids,['a','b']);
  const projected=explore(rows,{projection:'full'});
  assert.deepEqual(projected.pareto_ids,['a','b']);assert.deepEqual(projected.line_points,[]);
});
test('front is sorted in objective x for deterministic line and no interpolation results', () => {
  const r=explore([sample('a',{spot:1.648,fov:24}),sample('b',{spot:1.6,fov:24.72})]);
  assert.deepEqual(r.line_points.map(p=>p.id),['b','a']);
  assert.equal(r.axes[0].key,'spot');assert.equal(r.axes[0].direction,'minimize');
});
test('zero-weight dominated tie is not the weighted best', () => {
  const p=copy(profile);p.category_weights.mtf=0;
  const result=explore([sample('a'),sample('z',{quality:1.2})],{},p);
  assert.equal(result.best_id,'z');
});
test('no implicit mixing of source groups or conditions', () => {
  const rows=[sample('a'),sample('b',{source_kind:'zemax'}),sample('c',{cohort_key:'85C'})];
  const ambiguous=explore(rows);assert.equal(ambiguous.status,'source_required');assert.deepEqual(ambiguous.rows,[]);
  const result=explore(rows,{source_kind:'synthetic'});assert.deepEqual(result.rows.map(r=>r.id),['a']);
  assert.equal(Pareto.explore(evaluate(rows),{}).status,'cohort_required');
});
test('empty data and absent selected cohort return no fabricated result', () => {
  const result=explore([]);assert.equal(result.status,'ready');assert.equal(result.best_id,null);
  assert.deepEqual(result.line_points,[]);assert.deepEqual(explore([sample('a')],{cohort_key:'missing'}).rows,[]);
});
test('unsupported profile, units, comparator, zero target or extra required criterion fail closed', () => {
  const variants=[null,{}, {...copy(profile),profile_version:2}];
  for(const change of [t=>t.unit='percent',t=>t.comparator='<=',t=>t.value=0,t=>delete t.value]) {
    const p=copy(profile);change(p.targets[0]);variants.push(p);
  }
  const extra=copy(profile);extra.targets.push({id:'na',category:'na',metric:'na',comparator:'>=',value:.1,unit:'fraction',required:true});variants.push(extra);
  for(const p of variants) {const result=evaluate([sample('a')],p);assert.equal(result.status,'unsupported_profile');assert.deepEqual(result.rows,[]);assert.ok(result.errors.length);}
});
test('missing or invalid weights and all-zero weights fail closed', () => {
  for(const w of [{mtf:1,spot:1},{mtf:-1,spot:1,horizontal_fov:1},{mtf:0,spot:0,horizontal_fov:0}]) {
    const p=copy(profile);p.category_weights=w;assert.equal(evaluate([sample('a')],p).status,'unsupported_profile');
  }
});
test('invalid options and unsupported evaluation do not silently substitute defaults', () => {
  const e=evaluate([sample('a')]);
  assert.equal(Pareto.explore(e,{cohort_key:'20C-spectrum-v1',mode:'all'}).status,'invalid_options');
  assert.equal(Pareto.explore(e,{cohort_key:'20C-spectrum-v1',dimensions:['spot','na']}).status,'invalid_options');
  assert.equal(Pareto.explore(evaluate([],null),{cohort_key:'x'}).status,'unsupported_profile');
});
test('inputs remain unchanged including deeply frozen nested metadata and profile', () => {
  const rows=deepFreeze([sample('b'),sample('a')]);const p=deepFreeze(copy(profile));
  const before=JSON.stringify({rows,p});const result=Pareto.evaluateCases(rows,p);
  Pareto.explore(result,{cohort_key:'20C-spectrum-v1'});
  assert.equal(JSON.stringify({rows,p}),before);
});
test('finite very large weights retain finite normalized score', () => {
  const p=copy(profile);p.category_weights={mtf:1e308,spot:1e308,horizontal_fov:1e308};
  const ev=evaluate([sample('a',{quality:1.2})],p).rows[0].evaluation;
  assert.ok(Number.isFinite(ev.score));assert.ok(Math.abs(ev.score+1/15)<1e-12);
});
test('overflow in otherwise finite target ratios is UNKNOWN rather than an infinite front', () => {
  const p=copy(profile);p.targets.filter(t=>t.category==='mtf').forEach(t=>t.value=Number.MIN_VALUE);
  const e=evaluate([sample('a')],p);assert.equal(e.rows[0].evaluation.status,'UNKNOWN');
  assert.deepEqual(Pareto.explore(e,{cohort_key:'20C-spectrum-v1',mode:'exploratory'}).rows,[]);
});
test('null or primitive explore options fail closed', () => {
  for(const options of [null,1,'eligible',[]]) assert.equal(Pareto.explore(evaluate([sample('a')]),options).status,'invalid_options');
});
test('unsupported profile constraint fields cannot be silently ignored', () => {
  const p=copy(profile);p.constraints={na:{min:.2}};
  assert.equal(evaluate([sample('a')],p).status,'unsupported_profile');
});
test('same declared cohort with conflicting actual conditions is excluded', () => {
  const a=sample('a'),b=sample('b');b.temperature_c=85;b.conditions.temperature_c=85;
  const e=evaluate([a,b]);assert.ok(e.rows.every(r=>r.evaluation.status==='UNKNOWN'));
  assert.ok(e.rows.every(r=>r.evaluation.reasons.includes('COHORT_CONDITIONS_CONFLICT')));
});
test('exploratory NG with better score can appear on front but is never weighted best', () => {
  const rows=[sample('pass'),sample('ng',{quality:2,spot:1.7})];
  const result=explore(rows,{mode:'exploratory'});
  assert.ok(result.rows.find(r=>r.id==='ng').evaluation.score<result.rows.find(r=>r.id==='pass').evaluation.score);
  assert.ok(result.full_pareto_ids.includes('ng'));
  assert.equal(result.best_id,'pass');
  assert.equal(explore([rows[1]],{mode:'exploratory'}).best_id,null);
});
test('symmetric goal distances retain both designs on front and use deterministic best tie', () => {
  const rows=[sample('a-upper',{spot:1.68}),sample('z-lower',{spot:1.52})];
  const result=explore(rows);
  assert.deepEqual(result.pareto_ids,['a-upper','z-lower']);
  assert.deepEqual(result.full_pareto_ids,['a-upper','z-lower']);
  assert.equal(result.best_id,'a-upper');
});
test('numeric objective ties within 1e-12 remain ties while material differences dominate', () => {
  const result=explore([sample('a',{spot:1.6*(1+.02+5e-13)}),sample('b',{spot:1.6*1.02})]);
  assert.deepEqual(result.full_pareto_ids,['a','b']);assert.equal(result.best_id,'a');
  const distinct=explore([sample('a',{spot:1.6*(1+.02+5e-10)}),sample('b',{spot:1.6*1.02})]);
  assert.deepEqual(distinct.full_pareto_ids,['b']);assert.equal(distinct.best_id,'b');
});
test('conflicting duplicate case IDs are UNKNOWN and never selectable', () => {
  const result=explore([sample('duplicate'),sample('duplicate',{spot:1.632}),sample('safe')],{mode:'exploratory'});
  assert.deepEqual(result.rows.map(r=>r.id),['safe']);assert.equal(result.best_id,'safe');
  const e=evaluate([sample('duplicate'),sample('duplicate',{quality:1.1})]);
  assert.ok(e.rows.every(r=>r.evaluation.status==='UNKNOWN'));
  assert.ok(e.rows.every(r=>r.evaluation.reasons.includes('CONFLICTING_CASE_ID')));
});
test('same ID in separate sources or conditions is not a conflicting duplicate', () => {
  const e=evaluate([sample('id'),sample('id',{source_kind:'zemax'}),sample('id',{cohort_key:'another'})]);
  assert.ok(e.rows.every(r=>r.evaluation.status==='PASS'));
});
