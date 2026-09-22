const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const sandbox={window:{}};
vm.runInNewContext(fs.readFileSync('design/session-validation.js','utf8'),sandbox);
const validate=sandbox.window.validateOpticsWorkspaceSnapshot;
test('Pareto view preferences survive without cached results or execution state',()=>{
 const x=fixture();x.pareto_view={cohort_key:'cohort-a',source_kind:'synthetic',mode:'exploratory',
   dimensions:['mtf','spot'],projection:'full',show_line:false,selected_id:'C2'};
 const r=validate(x);assert.equal(JSON.stringify(r.pareto_view),JSON.stringify(x.pareto_view));
});
test('malformed Pareto axes and modes are rejected before restoration',()=>{
 const x=fixture();x.pareto_view={mode:'eligible',dimensions:['spot','spot'],projection:'pair',show_line:true};
 assert.throws(()=>validate(x));
 x.pareto_view.dimensions=['spot','horizontal_fov'];x.pareto_view.mode='execute';assert.throws(()=>validate(x));
});
function fixture(){
  return {ui_version:1,reference_data:{id:'case'},optics:{lens:0,side:0,section:false,layout:'studio',coverageExample:true,source:10,gaps:{gap12:2,gap23:2},lenses:Array.from({length:3},()=>({material:'N-BK7',type:'STANDARD',thickness:7,surfaces:Array.from({length:2},()=>({radius:30,conic:0,aperture:10,a4:0,a6:0,a8:0,a10:0,a12:null}))}))},parameters:{L0thickness:{active:true,min:1,max:12},L0S0a12:{active:false,min:null,max:null}},training:{learning_rate:0.001,epochs:100,gpu_location:'local',new_version:'v2'},automation:{hours:24,iterations:1000,window:100,improvement:0.5},view:'update',llm_draft:'draft',section_zoom:1,chart_views:{mtf:{k:2,x:-10,y:0}},camera:{position:[60,30,60],target:[24,0,0],zoom:1,fov:34}};
}
test('valid settings are copied and optical jobs never restored',()=>{
 const x=fixture(),copy=JSON.stringify(x),r=validate(x);
 assert.equal(r.optics.lenses[0].thickness,7);assert.equal(JSON.stringify(x),copy);
 x.view='sim';assert.equal(validate(x).view,'workspace');
});
test('invalid numeric range rejected before state mutation',()=>{
 const x=fixture();x.parameters.L0thickness.min=null;x.parameters.L0thickness.max='bad';
 assert.throws(()=>validate(x));assert.equal(x.optics.lenses[0].thickness,7);
});
test('unknown parameter IDs are rejected',()=>{
 const x=fixture();x.parameters.unknown={active:true,min:0,max:10};assert.throws(()=>validate(x));
});
test('A12 remains null and inactive',()=>{
 const x=fixture();x.parameters.L0S0a12.active=true;assert.throws(()=>validate(x));
 x.parameters.L0S0a12.active=false;x.optics.lenses[0].surfaces[0].a12=0;assert.throws(()=>validate(x));
});
test('out-of-range restored current values are rejected',()=>{
 const x=fixture();x.parameters.L0thickness.max=6;assert.throws(()=>validate(x));
});
test('training strings cannot reach numeric HTML attributes',()=>{
 const x=fixture();x.training.learning_rate='" autofocus onfocus="alert(1)';assert.throws(()=>validate(x));
});
test('invalid automation and GPU enums are rejected',()=>{
 const x=fixture();x.automation.iterations=1.5;assert.throws(()=>validate(x));
 x.automation.iterations=1000;x.training.gpu_location='remote-shell';assert.throws(()=>validate(x));
});
test('camera and chart shapes are checked',()=>{
 const x=fixture();x.camera.position=[1,'x',3];assert.throws(()=>validate(x));
 x.camera=null;x.chart_views.mtf.k=Infinity;assert.throws(()=>validate(x));
});
test('reserved keys cannot become state prototypes',()=>{
 const x=fixture();x.parameters=JSON.parse('{"__proto__":{"active":true,"min":1,"max":12}}');assert.throws(()=>validate(x));
});
test('sessions without ray visibility enable chief and marginal by default',()=>{
 const x=fixture();const r=validate(x);
 assert.deepEqual(JSON.parse(JSON.stringify(r.optics.ray_visibility)),{chief:true,marginal:true});
});
test('legacy paraxial visibility migrates to independently enabled chief and preserves marginal',()=>{
 for(const paraxial of [true,false])for(const marginal of [true,false]){
  const x=fixture();x.optics.ray_visibility={paraxial,marginal};const before=JSON.stringify(x);
  const r=validate(x);assert.deepEqual(JSON.parse(JSON.stringify(r.optics.ray_visibility)),{chief:true,marginal});
  assert.equal(JSON.stringify(x),before);
 }
});
test('invalid ray display flags are rejected before restore',()=>{
 const x=fixture();x.optics.ray_visibility={paraxial:'yes',marginal:true};assert.throws(()=>validate(x));
});
test('snapshots without stop receive the new farthest-surface default',()=>{
 const x=fixture(),before=JSON.stringify(x),r=validate(x);
 assert.deepEqual(JSON.parse(JSON.stringify(r.optics.stop)),{position_mode:'surface',surface_index:6,z_mm:null});
 assert.equal(JSON.stringify(x),before);
 assert.equal(Object.hasOwn(x.optics,'stop'),false);
});
test('surface-following stop is copied without becoming an absolute coordinate',()=>{
 const x=fixture();x.optics.stop={position_mode:'surface',surface_index:1,z_mm:null};
 const r=validate(x);
 assert.deepEqual(JSON.parse(JSON.stringify(r.optics.stop)),x.optics.stop);
 r.optics.stop.surface_index=2;
 assert.equal(x.optics.stop.surface_index,1);
});
test('absolute stop preserves finite nonnegative position including the origin',()=>{
 for(const z of [0,12.3456789,1000]){
  const x=fixture();x.optics.stop={position_mode:'absolute',surface_index:1,z_mm:z};
  assert.equal(validate(x).optics.stop.z_mm,z);
 }
});
test('stop survives validated JSON save and reopen roundtrip',()=>{
 const x=fixture();x.optics.stop={position_mode:'absolute',surface_index:1,z_mm:8.75};
 const saved=JSON.parse(JSON.stringify(validate(x))),reopened=validate(saved);
 assert.deepEqual(JSON.parse(JSON.stringify(reopened.optics.stop)),x.optics.stop);
});
test('stop mode and the one-through-six surface index are validated',()=>{
 const invalid=[
  null,[],{position_mode:'auto',surface_index:1,z_mm:null},
  {position_mode:'surface',surface_index:7,z_mm:null},
  {position_mode:'surface',surface_index:1.5,z_mm:null},
  {position_mode:'absolute',surface_index:0,z_mm:2},
  {position_mode:'absolute',surface_index:'1',z_mm:2},
  {position_mode:'absolute',surface_index:true,z_mm:2}
 ];
 for(const stop of invalid){const x=fixture();x.optics.stop=stop;assert.throws(()=>validate(x));}
});
test('stop coordinates obey surface-null versus absolute-finite contract',()=>{
 const invalid=[
  {position_mode:'surface',surface_index:1,z_mm:0},
  {position_mode:'surface',surface_index:1},
  {position_mode:'absolute',surface_index:1,z_mm:null},
  {position_mode:'absolute',surface_index:1,z_mm:-0.1},
  {position_mode:'absolute',surface_index:1,z_mm:NaN},
  {position_mode:'absolute',surface_index:1,z_mm:Infinity},
  {position_mode:'absolute',surface_index:1,z_mm:'3'}
 ];
 for(const stop of invalid){const x=fixture();x.optics.stop=stop;assert.throws(()=>validate(x));}
});
test('canonical stop does not persist a separate aperture diameter',()=>{
 const x=fixture();x.optics.stop={position_mode:'surface',surface_index:6,z_mm:null,diameter_mm:999};
 x.optics.lenses[2].surfaces[1].aperture=14;
 const r=validate(x);
 assert.deepEqual(Object.keys(r.optics.stop).sort(),['position_mode','surface_index','z_mm']);
 assert.equal(r.optics.stop.surface_index,6);
 assert.equal(r.optics.lenses[2].surfaces[1].aperture,14);
});
test('new chief choices survive canonical JSON roundtrip without legacy paraxial output',()=>{
 for(const chief of [true,false])for(const marginal of [true,false]){
  const x=fixture();x.optics.ray_visibility={chief,marginal};
  const saved=JSON.parse(JSON.stringify(validate(x))),reopened=validate(saved);
  assert.deepEqual(JSON.parse(JSON.stringify(reopened.optics.ray_visibility)),{chief,marginal});
 }
});
test('explicit chief takes precedence when both current and legacy flags are valid',()=>{
 const x=fixture();x.optics.ray_visibility={chief:false,paraxial:true,marginal:false};
 assert.deepEqual(JSON.parse(JSON.stringify(validate(x).optics.ray_visibility)),{chief:false,marginal:false});
});
test('invalid current legacy or incomplete visibility flags are rejected',()=>{
 const invalid=[
  {chief:'yes',marginal:true},{chief:true,paraxial:'no',marginal:true},
  {chief:false,paraxial:true,marginal:0},{paraxial:null,marginal:true},
  {marginal:true},{chief:true},{paraxial:true},null,[]
 ];
 for(const ray_visibility of invalid){const x=fixture();x.optics.ray_visibility=ray_visibility;assert.throws(()=>validate(x));}
});
test('explicit saved stop indices one through six are preserved in both position modes',()=>{
 for(const surface_index of [1,2,3,4,5,6])for(const position_mode of ['surface','absolute']){
  const x=fixture(),z_mm=position_mode==='surface'?null:8.75;
  x.optics.stop={position_mode,surface_index,z_mm};
  const r=validate(x);
  assert.deepEqual(JSON.parse(JSON.stringify(r.optics.stop)),x.optics.stop);
 }
});
