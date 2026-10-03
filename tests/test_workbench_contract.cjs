const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const sandbox={window:{}};
vm.runInNewContext(fs.readFileSync('design/workbench-contract.js','utf8'),sandbox);
const {validateParameterUpdate,validateShellState}=sandbox.window.OpticsWorkbenchContract;
const copy=x=>JSON.parse(JSON.stringify(x));

function parameters(){return {revision:'edit-17',materials:['N-BK7','N-F2'],
 lenses:[{index:0,material:'N-BK7',surface_type:'EVEN_ASPHERE'}],parameters:[
  {id:'radius',label:'Radius',group:'L1 / Front',unit:'mm',kind:'number',lens_index:0,
   coefficient:false,min:1,max:10,value:6,active:true,available:true},
  {id:'a4',label:'A4',group:'L1 / Front',unit:'mm^-3',kind:'number',lens_index:0,
   coefficient:true,min:-1e-5,max:1e-5,value:1.234567890123456e-20,active:true,available:true},
  {id:'a12',label:'A12',group:'L1 / Front',unit:'mm^-11',kind:'number',lens_index:0,
   coefficient:true,min:null,max:null,value:null,active:false,available:false},
  {id:'source',label:'Image plane → L1',group:'System',unit:'mm',kind:'number',
   min:1,max:35,value:12.5,active:false,available:true}]};}
function shell(){return {version:1,page:'workspace',llm_visible:true,analysis_visible:true,
 workspace_split:[820,340],explorer:{workspace_root:'/workspace',files:['main.py','docs/notes.md'],
 current_file:'main.py',wrap_lines:false},sensitivity:{format:'optics-sensitivity-panel',schema_version:1,
 metric:'ST',output_id:'mtf-0-sagittal',report_path:null,report:null,stale:false}};}
function rect(){return {x:-1280,y:-80,width:1280,height:720,maximized:false};}
function shellV2(){return {...shell(),version:2,layout:{window:rect(),llm_width:310,explorer_split:[240,800],
 charts:{mtf:{open:false,window:null},spot:{open:false,window:null}}}};}

test('v1 shell stays unchanged and does not invent new layout defaults',()=>{
 const x=shell(),result=validateShellState(x);assert.deepEqual(copy(result),x);assert.equal(Object.hasOwn(result,'layout'),false);
});
test('v2 layout and independent chart windows are copied with negative coordinates',()=>{
 const x=shellV2();x.layout.charts.mtf={open:true,window:rect()};const before=copy(x);
 const result=validateShellState(x);assert.deepEqual(copy(result),x);
 result.layout.window.x=100;result.layout.charts.mtf.window.y=100;result.layout.explorer_split[0]=10;
 assert.deepEqual(x,before);
});
test('v2 null window geometry is preserved and sim still restores workspace',()=>{
 const x=shellV2();x.layout.window=null;x.layout.charts.mtf.open=true;x.layout.explorer_split=[0,800];x.page='sim';
 const result=validateShellState(x);assert.equal(result.layout.window,null);assert.equal(result.layout.charts.mtf.window,null);
 assert.equal(result.page,'workspace');
});
test('v2 exact layout and chart keys reject omissions and unrelated state',()=>{
 const mutations=[x=>delete x.layout,x=>x.layout=null,x=>x.layout.extra=true,x=>delete x.layout.llm_width,
  x=>delete x.layout.charts.spot,x=>x.layout.charts.other={},x=>delete x.layout.charts.mtf.window,
  x=>x.layout.charts.mtf.open=1,x=>x.layout.charts.spot.extra=1];
 for(const mutate of mutations){const x=shellV2();mutate(x);assert.throws(()=>validateShellState(x));}
 for(const version of [1,3,true]){const x=shellV2();x.version=version;assert.throws(()=>validateShellState(x));}
});
test('main and chart rectangles enforce identical Qt signed coordinates and positive sizes',()=>{
 const bad=[['x',-2147483649],['x',2147483648],['y',false],['y',1.5],['width',0],['width',16777216],
  ['height',-1],['height','720'],['maximized',1],['extra',10]];
 for(const location of ['main','chart'])for(const [key,value]of bad){
  const x=shellV2(),window=location==='main'?x.layout.window:rect();window[key]=value;
  if(location==='chart')x.layout.charts.spot.window=window;assert.throws(()=>validateShellState(x));
 }
 const x=shellV2();Object.assign(x.layout.window,{x:-2147483648,y:2147483647,width:16777215,height:1,maximized:true});
 assert.deepEqual(copy(validateShellState(x)),x);
});
test('v2 LLM width and Explorer split reject invalid sizes',()=>{
 for(const [key,value]of [['llm_width',0],['llm_width',16777216],['llm_width',true],['llm_width',310.5],
  ['explorer_split',[0,0]],['explorer_split',[-1,5]],['explorer_split',[10]],['explorer_split',[1.2,20]],['explorer_split',[2147483648,5]]]){
  const x=shellV2();x.layout[key]=value;assert.throws(()=>validateShellState(x));
 }
});

test('parameter request produces a detached result preserving revision and precision',()=>{
 const baseline=parameters(),request=copy(baseline),before=copy(baseline);
 request.parameters[1].value=-2.345678901234567e-22;
 const result=validateParameterUpdate(baseline,request);
 assert.equal(result.revision,'edit-17');assert.equal(result.parameters[1].value,request.parameters[1].value);
 result.parameters[0].value=9;assert.deepEqual(baseline,before);assert.equal(request.parameters[0].value,6);
});
test('edited range clamps only that row, preserving all other numbers exactly',()=>{
 const baseline=parameters(),request=copy(baseline);request.parameters[0].min=8;
 const result=copy(validateParameterUpdate(baseline,request));
 assert.equal(result.parameters[0].value,8);assert.deepEqual(result.parameters.slice(1),baseline.parameters.slice(1));
});
test('stale revisions and incomplete duplicate unknown IDs are rejected before mutation',()=>{
 const baseline=parameters(),before=copy(baseline);
 for(const mutate of [x=>x.revision='old',x=>x.parameters.pop(),
   x=>x.parameters.push(copy(x.parameters[0])),x=>x.parameters[0].id='new']){
  const request=copy(baseline);mutate(request);assert.throws(()=>validateParameterUpdate(baseline,request));
  assert.deepEqual(baseline,before);
 }
});
test('request order does not reorder baseline parameter identity',()=>{
 const baseline=parameters(),request=copy(baseline);request.parameters.reverse();
 assert.deepEqual(copy(validateParameterUpdate(baseline,request)).parameters,baseline.parameters);
});
test('invalid finite range scalar and boolean fields are rejected',()=>{
 const baseline=parameters();
 for(const change of [{value:NaN},{value:Infinity},{value:'6'},{value:true},{min:10},{min:11},
   {active:1},{available:'true'},{lens_index:1},{coefficient:true},{kind:'choice'}]){
  const request=copy(baseline);Object.assign(request.parameters[0],change);
  assert.throws(()=>validateParameterUpdate(baseline,request),JSON.stringify(change));
 }
});
test('A12 placeholder is immutable null and never activated',()=>{
 const baseline=parameters();
 for(const change of [{value:0},{min:0,max:1},{active:true}]){
  const request=copy(baseline);Object.assign(request.parameters[2],change);
  assert.throws(()=>validateParameterUpdate(baseline,request));
 }
 const request=copy(baseline);request.parameters[2].available=true;
 assert.equal(validateParameterUpdate(baseline,request).parameters[2].available,false);
});
test('availability is recomputed from final lens type while configured active and coefficient value survive',()=>{
 const baseline=parameters(),request=copy(baseline);request.lenses[0].surface_type='STANDARD';
 request.parameters[0].available=false;request.parameters[1].available=true;
 const result=validateParameterUpdate(baseline,request);
 assert.equal(result.parameters[0].available,true);assert.equal(result.parameters[1].available,false);
 assert.equal(result.parameters[1].active,true);assert.equal(result.parameters[1].value,baseline.parameters[1].value);
 const back=copy(result);back.lenses[0].surface_type='EVEN_ASPHERE';
 assert.equal(validateParameterUpdate(copy(result),back).parameters[1].available,true);
});
test('lens count material and surface type cannot escape baseline choices',()=>{
 const baseline=parameters();
 for(const mutate of [x=>x.lenses=[],x=>x.lenses[0].index=2,x=>x.lenses[0].material='UNKNOWN',
 x=>x.lenses[0].surface_type='TOROIDAL',x=>x.materials.push('UNKNOWN')]){
  const request=copy(baseline);mutate(request);assert.throws(()=>validateParameterUpdate(baseline,request));
 }
 const request=copy(baseline);request.lenses[0].material='N-F2';
 assert.equal(validateParameterUpdate(baseline,request).lenses[0].material,'N-F2');
});
test('prototype keys and non-JSON values are rejected at every depth',()=>{
 const baseline=parameters();
 for(const key of ['__proto__','constructor','prototype']){
  const request=copy(baseline);request.extra=JSON.parse('{"'+key+'":{}}');
  assert.throws(()=>validateParameterUpdate(baseline,request));
 }
 const request=copy(baseline);request.extra=()=>1;assert.throws(()=>validateParameterUpdate(baseline,request));
});
test('shell preferences are detached and sim is normalized to workspace',()=>{
 const x=shell(),before=copy(x);x.page='sim';
 const result=validateShellState(x);assert.equal(result.page,'workspace');
 result.explorer.files.push('extra.py');assert.deepEqual(x.explorer,before.explorer);
});
test('all independent page routes and optional missing report state are valid',()=>{
 for(const page of ['workspace','explorer','tailoring','update','sim','auto']){
  const x=shell();x.page=page;x.sensitivity=null;
  assert.equal(validateShellState(x).page,page==='sim'?'workspace':page);
 }
});
test('shell booleans version splitter and page types are strict',()=>{
 for(const change of [{version:true},{version:2},{page:'execute'},{llm_visible:1},{analysis_visible:'yes'},
  {workspace_split:[1]},{workspace_split:[1,2.5]},{workspace_split:[-1,10]},{workspace_split:[0,0]},
  {workspace_split:[2147483648,10]}]){
  const x=shell();Object.assign(x,change);assert.throws(()=>validateShellState(x));
 }
 const x=shell();x.workspace_split=[1000,0];assert.equal(validateShellState(x).workspace_split[1],0);
});
test('workspace roots preserve POSIX Windows-drive and UNC absolute strings',()=>{
 for(const path of ['/workspace','C:\\Users\\designer\\optics','D:/Projects/Optics','\\\\server\\share\\optics']){
  const x=shell();x.explorer.workspace_root=path;
  assert.equal(validateShellState(x).explorer.workspace_root,path);
 }
 for(const path of ['', 'relative/project','C:relative','\\server','/workspace\0']){
  const x=shell();x.explorer.workspace_root=path;assert.throws(()=>validateShellState(x));
 }
});
test('shell and explorer fields are exact rather than silently discarding unknown settings',()=>{
 for(const mutate of [x=>x.job='running',x=>delete x.llm_visible,
   x=>x.explorer.execute=true,x=>delete x.explorer.wrap_lines]){
  const x=shell();mutate(x);assert.throws(()=>validateShellState(x));
 }
});
test('source tabs are at most 64 unique normalized relative POSIX paths',()=>{
 for(const path of ['/tmp/a.py','C:/a.py','C:a.py','../a.py','a/../b.py','a\\b.py','a\0b.py','a//b.py','./a.py','']){
  const x=shell();x.explorer.files=[path];x.explorer.current_file=path;
  assert.throws(()=>validateShellState(x),path);
 }
 const x=shell();x.explorer.files=Array.from({length:65},(_,i)=>i+'.py');x.explorer.current_file=null;
 assert.throws(()=>validateShellState(x));x.explorer.files=['a.py','a.py'];assert.throws(()=>validateShellState(x));
});
test('current source must be an opened file and wrap_lines is a boolean',()=>{
 const x=shell();x.explorer.current_file='missing.py';assert.throws(()=>validateShellState(x));
 x.explorer.current_file=null;x.explorer.wrap_lines=0;assert.throws(()=>validateShellState(x));
 x.explorer.wrap_lines=true;assert.equal(validateShellState(x).explorer.current_file,null);
});
test('sensitivity validates panel types and finite JSON without claiming scientific validation',()=>{
 for(const mutate of [p=>p.metric='S2',p=>p.output_id=4,p=>p.report=[],p=>p.stale='yes',
  p=>p.schema_version=2,p=>p.report={arbitrary:{estimate:NaN}}]){
  const x=shell();mutate(x.sensitivity);assert.throws(()=>validateShellState(x));
 }
 const x=shell();x.sensitivity.report={format:'optics-sobol-report',schema_version:1,requires_native_validation:true};
 assert.deepEqual(copy(validateShellState(x)).sensitivity.report,x.sensitivity.report);
});
test('shell prototype keys cannot be smuggled through embedded reports',()=>{
 const x=shell();x.sensitivity.report=JSON.parse('{"nested":{"__proto__":{}}}');
 assert.throws(()=>validateShellState(x));
});
