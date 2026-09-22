const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('design/optics-workspace-concept.html','utf8');
const start=source.indexOf('function resolveRayInputs('),end=source.indexOf('let rayCache=',start);
assert.ok(start>=0&&end>start,'ray input adapter must exist');
const api={};vm.runInNewContext(source.slice(start,end),api);
const display={temperature:20,wavelengths:[450,546.074,656.2725]};
function reference(){return {analysis_conditions:{primary_wavelength_nm:546.074},ray_indices:{status:'available',wavelength_nm:546.074,temperature_c:20,indices:{glass:1.5187,polymer:1.49}}}}
test('uses primary-wavelength exact samples and keeps all selectable materials',()=>{
 const r=api.resolveRayInputs(reference(),display);assert.equal(r.wavelength_nm,546.074);assert.equal(r.indices.glass,1.5187);assert.equal(r.indices.polymer,1.49);
});
test('wrong wavelength or temperature never silently supplies old indices',()=>{
 const d=reference();d.ray_indices.wavelength_nm=587.5618;assert.equal(Object.keys(api.resolveRayInputs(d,display).indices).length,0);
 d.ray_indices.wavelength_nm=546.074;d.ray_indices.temperature_c=25;assert.equal(Object.keys(api.resolveRayInputs(d,display).indices).length,0);
});
test('missing or invalid indices receive no guessed glass defaults',()=>{
 const d=reference();d.ray_indices.indices={glass:'1.5',polymer:NaN};assert.equal(Object.keys(api.resolveRayInputs(d,display).indices).length,0);
 delete d.ray_indices;assert.equal(Object.keys(api.resolveRayInputs(d,display).indices).length,0);
});
test('partial catalog preserves verified values only',()=>{
 const d=reference();d.ray_indices.status='partial';delete d.ray_indices.indices.polymer;
 const r=api.resolveRayInputs(d,display);assert.equal(r.indices.glass,1.5187);assert.equal(r.indices.polymer,undefined);
});
