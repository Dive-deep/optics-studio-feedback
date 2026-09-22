const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('design/optics-workspace-concept.html','utf8');
function fragment(start,end){const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a,`${start} exists`);return source.slice(a,b)}
function workspace(status='ready'){
  const elements=new Map();
  function byId(id){if(!elements.has(id))elements.set(id,{hidden:false,disabled:false,textContent:'',innerHTML:'',classList:{add(){},remove(){}},setAttribute(){},removeAttribute(){},toggleAttribute(name,value){this[name]=value}});return elements.get(id)}
  const scope={state:{section:false,layout:'studio'},draws:0,events:0,byId,
    drawSection(){scope.draws++},renderCharts(){},renderParams(){},updateReadouts(){},
    CustomEvent:class{constructor(type){this.type=type}},requestAnimationFrame:fn=>fn(),
    settings:{},coverageBaselines:{},conditions:{},trainingSettings:{},autoSettings:{},chartViews:{},
    paretoPanel:null,actions:{},computeRevision:0,activeView:'workspace',resolveConditions:()=>({}),
    validateSnapshot:x=>x,
    root:{dataset:{webgl:status},classList:{toggle(){}},dispatchEvent(){scope.events++},querySelector:byId}};
  scope.stopHandle=byId('o-stop-handle');
  vm.runInNewContext(fragment('function syncViewerMode(', 'let activeView='),scope);
  vm.runInNewContext(fragment('function workspace(){','function targets(){'),scope);
  vm.runInNewContext(fragment('function restoreSession(','function notice('),scope);
  return scope;
}
test('WebGL failure keeps the section visible and explains the unavailable 3D control',()=>{
  const s=workspace();s.root.__setWebGLUnavailable('webgl2-unavailable');
  assert.equal(s.state.section,true);assert.equal(s.byId('o-canvas').hidden,true);
  assert.equal(s.byId('o-section').hidden,false);assert.equal(s.byId('o-view-toggle').disabled,true);
  assert.equal(s.byId('o-webgl-status').hidden,false);assert.match(s.byId('o-webgl-status').textContent,/3D.*2D/);
  assert.equal(s.draws,1);
});
test('a workspace opened after applying a 3D case still respects failed runtime graphics',()=>{
  const s=workspace('failed');s.state.section=false;s.workspace();
  assert.equal(s.state.section,true);assert.equal(s.byId('o-canvas').hidden,true);
  assert.equal(s.byId('o-section').hidden,false);assert.equal(s.byId('o-view-toggle').disabled,true);
});
test('restoring a session saved in 3D cannot restore an unavailable canvas',()=>{
  const s=workspace('failed');
  s.restoreSession({reference_data:{},optics:{section:false,layout:'studio'},parameters:{},training:{},automation:{},llm_draft:'',section_zoom:1,chart_views:{},camera:null,view:'workspace'});
  assert.equal(s.state.section,true);assert.equal(s.byId('o-section').hidden,false);
  assert.equal(s.byId('o-webgl-status').hidden,false);assert.equal(s.byId('o-view-toggle').disabled,true);
});
test('failed 3D stays unavailable even if the click callback is invoked programmatically',()=>{
  const s=workspace('failed');s.syncViewerMode();s.byId('o-view-toggle').onclick();
  assert.equal(s.state.section,true);assert.equal(s.byId('o-canvas').hidden,true);
});
test('healthy graphics retain both normal viewer modes',()=>{
  const s=workspace('ready');s.syncViewerMode();
  assert.equal(s.byId('o-view-toggle').disabled,false);assert.equal(s.byId('o-webgl-status').hidden,true);
  assert.equal(s.byId('o-canvas').hidden,false);assert.equal(s.byId('o-view-toggle').textContent,'2D section view');
  s.byId('o-view-toggle').onclick();assert.equal(s.state.section,true);assert.equal(s.byId('o-view-toggle').textContent,'3D viewer');
  s.byId('o-view-toggle').onclick();assert.equal(s.state.section,false);assert.equal(s.byId('o-canvas').hidden,false);
});
function runScene({context=null,rendererError=null}={}){
  let constructors=0;const failures=[],errors=[];
  const canvas={getContext:()=>context,addEventListener(){}};
  const root={dataset:{},__opticsState:{section:false},querySelector:id=>id==='#o-canvas'?canvas:{},__setWebGLUnavailable:reason=>failures.push(reason)};
  const script=source.slice(source.lastIndexOf('<script type="module">')+22,source.lastIndexOf('</script>')).replace(/^\s*import .*;$/gm,'');
  vm.runInNewContext(script,{document:{getElementById:()=>root},THREE:{WebGLRenderer:class{constructor(){constructors++;throw rendererError||new Error('Renderer must not be constructed without a context')}}},console:{error:(...args)=>errors.push(args)},devicePixelRatio:1});
  return {constructors,failures,errors};
}
test('missing WebGL2 context uses normal fallback before creating Three renderer',()=>{
  const r=runScene();assert.equal(r.constructors,0);assert.deepEqual(r.failures,['webgl2-unavailable']);assert.equal(r.errors.length,0);
});
test('unexpected renderer failures are reported while keeping the 2D fallback',()=>{
  const error=new Error('unexpected renderer failure');const r=runScene({context:{},rendererError:error});
  assert.equal(r.constructors,1);assert.deepEqual(r.failures,['renderer-error']);assert.equal(r.errors.length,1);assert.ok(r.errors[0].includes(error));
});
