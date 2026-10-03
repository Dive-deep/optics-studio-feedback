const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const window={};vm.runInNewContext(fs.readFileSync('design/optics-chart.js','utf8'),{window});
const chart=window.OpticsChart,copy=x=>JSON.parse(JSON.stringify(x));
function payload(kind='mtf'){return {schema_version:1,kind,revision:'chart-1',reference_id:'D1',source_label:'합성 DB',
 conditions_label:'20°C · 5 wavelengths',condition_metadata:{temperature_c:20},
 units:{x:kind==='mtf'?'lp/mm':'µm',y:kind==='mtf'?'fraction':'µm'},rms_diameter_um:kind==='spot'?1.6:null,view:null,
 ...(kind==='mtf'?{mtf:[{field_norm:0,orientation:'TANGENTIAL',frequency_lp_per_mm:6,mtf:.3},
 {field_norm:0,orientation:'SAGITTAL',frequency_lp_per_mm:6,mtf:.4},{field_norm:0,orientation:'SAGITTAL',frequency_lp_per_mm:0,mtf:1}]}:
 {spot:[{x:1.25,y:-.5,wavelength_nm:546.074}]})};}
test('MTF preserves field and direction, sorting frequencies within each distinct curve',()=>{
 const source=payload(),before=copy(source),normalized=chart.normalizePayload(source),series=chart.mtfSeries(normalized);
 assert.equal(series.length,2);const sagittal=series.find(s=>s.orientation==='SAGITTAL');
 assert.deepEqual(copy(sagittal.values.map(p=>p.frequency_lp_per_mm)),[0,6]);
 assert.equal(sagittal.values[1].mtf,.4);assert.deepEqual(source,before);
});
test('MTF hover interpolation is bounded to a series and handles one-point series',()=>{
 const series=chart.mtfSeries(chart.normalizePayload(payload()));
 const sagittal=series.find(s=>s.orientation==='SAGITTAL'),tangential=series.find(s=>s.orientation==='TANGENTIAL');
 assert.ok(Math.abs(chart.mtfAt(sagittal,3)-.7)<1e-12);
 assert.equal(chart.mtfAt(sagittal,7),null);assert.equal(chart.mtfAt(tangential,6),.3);assert.equal(chart.mtfAt(tangential,3),null);
});
test('Spot coordinates are already micrometres and RMS remains diameter',()=>{
 const normalized=chart.normalizePayload(payload('spot'));
 assert.equal(normalized.spot[0].x,1.25);assert.equal(normalized.spot[0].y,-.5);
 assert.equal(normalized.units.x,'µm');assert.equal(normalized.rms_diameter_um,1.6);
});
test('empty result arrays remain missing rather than synthesizing a curve or spot',()=>{
 const p=payload();p.mtf=[];assert.equal(chart.normalizePayload(p).mtf.length,0);
 const spot=payload('spot');spot.spot=[];spot.rms_diameter_um=null;
 assert.equal(chart.normalizePayload(spot).rms_diameter_um,null);
});
test('nonfinite values, duplicate MTF samples, wrong units and invalid view are rejected',()=>{
 for(const mutate of [p=>p.mtf[0].mtf=NaN,p=>p.mtf.push({...p.mtf[0]}),p=>p.units.y='percent',
  p=>p.view={k:20,x:0,y:0},p=>p.mtf[0].orientation='OTHER']){
  const p=payload();mutate(p);assert.throws(()=>chart.normalizePayload(p));
 }
 const p=payload('spot');p.spot[0].x=Infinity;assert.throws(()=>chart.normalizePayload(p));
});
