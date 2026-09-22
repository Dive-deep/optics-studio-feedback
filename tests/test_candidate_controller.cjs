const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../design/file-controller.js'),'utf8');
const tick=()=>new Promise(setImmediate);
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
function harness(overrides={}){
  const applied=[],changes=[],calls=[];let sequence=0;
  const window={opticsBridge:{onReportLoaded(){},request:async(method,p)=>{
    calls.push({method,p});
    if(overrides[method])return overrides[method](p);
    if(method==='load_report')return {status:'valid',report_path:p.path,database_path:p.path+'.db',model_path:'model.pth'};
    if(method==='list_cases')return {cases:[{id:'C1',status:'SUCCESS',ui_compatible:true}]};
    if(method==='load_case')return {id:p.case_id};
    if(method==='candidate_data')return {schema_version:1,cases:[{id:p.path}],sequence:++sequence};
    throw Error(method);
  }}};
  vm.runInNewContext(source,{window});
  const controller=window.createOpticsFileController({enableCandidates:true,
    contextChanged:c=>changes.push(JSON.parse(JSON.stringify(c))),applyCase:c=>applied.push(c.id),
    snapshot:()=>({reference_data:{id:'C1'}}),restore(){},notice(){},error(e){throw e}});
  return {controller,applied,changes,calls};
}
test('report commit automatically loads an actual DB candidate pool',async()=>{
  const h=harness();await h.controller.loadReport('A');await tick();
  assert.equal(h.controller.getContext().candidateStatus,'ready');
  assert.equal(h.controller.getContext().candidateData.cases[0].id,'A.db');
});
test('an old DB candidate response never replaces the newly selected DB',async()=>{
  const pending=deferred(),h=harness({candidate_data:p=>p.path==='A.db'?pending.promise:{cases:[{id:'B'}]}});
  await h.controller.loadReport('A');await h.controller.loadReport('B');await tick();
  pending.resolve({cases:[{id:'A'}]});await tick();
  assert.equal(h.controller.getContext().candidateData.cases[0].id,'B');
});
test('latest refresh owns the candidate response and shows loading without stale data',async()=>{
  const h=harness();await h.controller.loadReport('A');await tick();
  const previous=h.controller.getContext().candidateData.sequence;
  await h.controller.refreshCandidates();
  assert.ok(h.controller.getContext().candidateData.sequence>previous);
  assert.ok(h.changes.some(c=>c.candidateStatus==='loading'&&c.candidateData===null));
});
test('candidate-read errors are local state and do not destroy the loaded workspace',async()=>{
  const h=harness({candidate_data:()=>Promise.reject(Object.assign(Error('Candidate metadata missing'),{code:'CANDIDATES'}))});
  await h.controller.loadReport('A');await tick();
  assert.equal(h.controller.getContext().report.report_path,'A');
  assert.equal(h.controller.getContext().candidateStatus,'error');
  assert.equal(h.controller.getContext().candidateError.code,'CANDIDATES');
  assert.deepEqual(h.applied,['C1']);
});
test('a stale target/cohort selection can reject applying an in-flight candidate',async()=>{
  const pending=deferred();let current=true;
  const h=harness({load_case:p=>p.case_id==='C2'?pending.promise:{id:p.case_id}});
  await h.controller.loadReport('A');await tick();
  const selecting=h.controller.selectCase('C2',{isCurrent:()=>current});current=false;
  pending.resolve({id:'C2'});assert.equal(await selecting,null);
  assert.deepEqual(h.applied,['C1']);
});
test('refresh without a connected database returns an unavailable state',async()=>{
  const h=harness();assert.equal(await h.controller.refreshCandidates(),null);
  assert.equal(h.controller.getContext().candidateStatus,'unavailable');
  assert.equal(h.calls.length,0);
});
