const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const copy=x=>JSON.parse(JSON.stringify(x));
function setup(native=true,overrides={}){
 const events=[],actions=[],state={view:'workspace',llm_draft:'draft',model_label:'model.pth',analysis_context:{},
  parameter_payload:{revision:'r1',materials:['N-BK7'],lenses:[{index:0,material:'N-BK7',surface_type:'STANDARD'}],
   parameters:[{id:'thickness',label:'Thickness',group:'L1',unit:'mm',kind:'number',lens_index:0,
    min:1,max:12,value:6,active:true,available:true}]}};
 const window={opticsBridge:{ready:Promise.resolve(true),workbench:native?{notify:raw=>events.push(JSON.parse(raw))}:null}};
 const sandbox={window,queueMicrotask};
 for(const path of ['design/workbench-contract.js','design/workbench-adapter.js'])vm.runInNewContext(fs.readFileSync(path,'utf8'),sandbox);
 let applied=0,shell=null;
 const api=window.createOpticsWorkbenchAdapter({getState:()=>state,
  getChartData:kind=>({schema_version:1,kind,revision:'chart-r1',view:null}),
  getSessionSnapshot:()=>({snapshot:{llm_draft:state.llm_draft},references:{report_path:null},session_fingerprint:'fp:'+state.llm_draft}),
  setChartView:payload=>{state.chart_view=copy(payload.view);},
  actions:Object.fromEntries(['workspace','update','sim','auto','model','open','save','export','targets','candidates','configure']
   .map(action=>[action,async()=>{actions.push(action);state.view=action;return {action};}])),
  applyParameters:payload=>{applied++;state.parameter_payload=copy(payload);state.parameter_payload.revision='r'+(applied+1);},
  setShellState:value=>{shell=value;},setLlmDraft:draft=>{state.llm_draft=draft;},
  setNativeMode:enabled=>actions.push('native:'+enabled),...overrides});
 return {window,api,state,events,actions,get applied(){return applied},get shell(){return shell}};
}
test('native ready announces complete state only after API installation',async()=>{
 const x=setup();await x.api.ready;
 assert.equal(x.window.opticsWorkbench,x.api);assert.equal(x.api.native,true);
 assert.equal(x.events[0].type,'ready');assert.equal(x.events[0].payload.parameter_payload.revision,'r1');
 assert.equal(x.events[1].type,'state');assert.ok(x.actions.includes('native:true'));
});
test('legacy desktop without native workbench keeps its original UI',async()=>{
 const x=setup(false);await x.api.ready;assert.equal(x.api.native,false);assert.deepEqual(x.events,[]);
 assert.equal(x.api.requestParameters(),false);assert.equal(x.api.toggleLlm(),false);
});
test('navigation uses a page whitelist and existing actions without creating editor tabs',async()=>{
 const x=setup();await x.api.ready;
 for(const page of ['workspace','update','sim','auto'])assert.equal((await x.api.command('navigate',{page})).action,page);
 await assert.rejects(x.api.command('navigate',{page:'explorer'}));
 await assert.rejects(x.api.command('execute_python',{}));
});
test('file actions await completion and return the actual result',async()=>{
 const x=setup();await x.api.ready;
 for(const action of ['model','open','save','export','targets','candidates','configure'])
  assert.equal((await x.api.command(action,{})).action,action);
});
test('parameter requests contain the exact detached native dialog payload',async()=>{
 const x=setup();await x.api.ready;x.api.requestParameters();
 const event=x.events.at(-1);assert.equal(event.type,'parameters_requested');assert.deepEqual(event.payload,x.state.parameter_payload);
 event.payload.parameters[0].value=8;assert.equal(x.state.parameter_payload.parameters[0].value,6);
});
test('parameter update validates atomically and rejects a stale second application',async()=>{
 const x=setup();await x.api.ready;const request=copy(x.state.parameter_payload);request.parameters[0].min=8;
 await x.api.command('apply_parameters',request);assert.equal(x.applied,1);assert.equal(x.state.parameter_payload.parameters[0].value,8);
 await assert.rejects(x.api.command('apply_parameters',request));assert.equal(x.applied,1);
 const invalid=copy(x.state.parameter_payload);invalid.parameters[0].max=7;
 await assert.rejects(x.api.command('apply_parameters',invalid));assert.equal(x.applied,1);
});
test('LLM toggle preserves central view and draft editing does not send a provider request',async()=>{
 const x=setup();await x.api.ready;x.api.toggleLlm();assert.equal(x.events.at(-1).type,'llm_toggle');
 assert.equal(x.state.view,'workspace');await x.api.command('set_llm_draft',{draft:'new draft'});
 assert.equal(x.state.llm_draft,'new draft');await assert.rejects(x.api.command('set_llm_draft',{draft:42}));
});
test('shell state is validated and restored event precedes the new state notification',async()=>{
 const x=setup();await x.api.ready;
 const shell={version:1,page:'sim',llm_visible:true,analysis_visible:true,workspace_split:[550,250],
  explorer:{workspace_root:'/workspace',files:[],current_file:null,wrap_lines:false},sensitivity:null};
 await x.api.command('set_shell_state',shell);assert.equal(x.shell.page,'workspace');
 x.api.sessionRestored(x.shell);assert.equal(x.events.at(-2).type,'session_restored');assert.equal(x.events.at(-1).type,'state');
 assert.equal(x.events.at(-2).payload.workbench.page,'workspace');
});
test('get_state is detached and repeated changed events are coalesced',async()=>{
 const x=setup();await x.api.ready;const r=await x.api.command('get_state');r.parameter_payload.parameters[0].value=99;
 assert.equal(x.state.parameter_payload.parameters[0].value,6);
 const count=x.events.length;x.api.changed();x.api.changed();await Promise.resolve();assert.equal(x.events.length,count+1);
});
test('bridge publishes native transport before its ready promise resolves',async()=>{
 let initialize;const workbench={notify(){},commandResult(){}},desktop={responseReady:{connect(){}},reportLoaded:{connect(){}},reportLoadStarted:{connect(){}}};
 const window={qt:{webChannelTransport:{}},dispatchEvent(){}};
 const sandbox={window,qt:window.qt,Event:class{},setTimeout,clearTimeout,QWebChannel:function(_,callback){initialize=callback;}};
 vm.runInNewContext(fs.readFileSync('design/bridge-client.js','utf8'),sandbox);
 let seen=null;const ready=window.opticsBridge.ready.then(()=>{seen=window.opticsBridge.workbench;});
 initialize({objects:{desktop,workbench}});await ready;assert.equal(seen,workbench);
});
test('native chart requests preserve central view and identify independent chart kinds',async()=>{
 const x=setup();await x.api.ready;
 for(const kind of ['mtf','spot']){
  assert.equal(x.api.requestChart(kind),true);
  assert.equal(x.events.at(-1).type,'chart_requested');assert.equal(x.events.at(-1).payload.kind,kind);
  assert.equal((await x.api.command('get_chart_data',{kind})).revision,'chart-r1');
 }
 assert.equal(x.state.view,'workspace');await assert.rejects(x.api.command('get_chart_data',{kind:'execute'}));
 const legacy=setup(false);await legacy.api.ready;assert.equal(legacy.api.requestChart('mtf'),false);
});
test('chart view update is validated and stale chart windows cannot overwrite current view',async()=>{
 const x=setup();await x.api.ready;
 await x.api.command('set_chart_view',{kind:'mtf',revision:'chart-r1',view:{k:2,x:10,y:0}});
 assert.deepEqual(x.state.chart_view,{k:2,x:10,y:0});
 for(const payload of [{kind:'mtf',revision:'old',view:{k:2,x:0,y:0}},
  {kind:'spot',revision:'chart-r1',view:{k:99,x:0,y:0}},
  {kind:'spot',revision:'chart-r1',view:{k:2,x:Infinity,y:0}}])await assert.rejects(x.api.command('set_chart_view',payload));
});
test('authoritative session snapshot is detached and open receipt follows completed file load',async()=>{
 let finish;const pending=new Promise(resolve=>{finish=resolve});
 const x=setup(true,{actions:{open:()=>pending}});await x.api.ready;
 const snapshot=await x.api.command('get_session_snapshot');snapshot.snapshot.llm_draft='changed';assert.equal(x.state.llm_draft,'draft');
 const operation=x.api.command('open');assert.equal(x.events.some(e=>e.type==='session_opened'),false);
 x.state.llm_draft='restored';finish({status:'loaded'});await operation;
 assert.equal(x.events.at(-1).type,'session_opened');assert.equal(x.events.at(-1).payload.session_fingerprint,'fp:restored');
});
test('canonical session fingerprint ignores native shell but includes references and UI state',()=>{
 const x=setup(),fingerprint=x.window.opticsSessionFingerprint;
 const snapshot={ui_version:1,optics:{source:10},chart_views:{},llm_draft:'',camera:null,workbench:{page:'workspace'}};
 const refs={report_path:null,database_path:null,target_path:null};
 const initial=fingerprint(snapshot,refs);
 const reordered={...snapshot,optics:{source:10},workbench:{page:'explorer'},camera:{position:[67,34,63],target:[24,0,0],zoom:1,fov:34}};
 assert.equal(fingerprint(reordered,{target_path:null,database_path:null,report_path:null}),initial);
 for(const change of [{llm_draft:'edit'},{chart_views:{mtf:{k:2,x:0,y:0}}},{optics:{source:11}}])assert.notEqual(fingerprint({...snapshot,...change},refs),initial);
 assert.notEqual(fingerprint(snapshot,{...refs,report_path:'/report.json'}),initial);
 assert.equal(snapshot.camera,null);
});
