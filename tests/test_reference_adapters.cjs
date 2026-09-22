const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('design/optics-workspace-concept.html','utf8');
function extract(start,end){return source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));}
const scope={};
vm.runInNewContext(extract('function resolveConditions(', 'const conditions='),scope);
test('resolved display fallbacks keep their provenance',()=>{
 const r=scope.resolveConditions({temperature_c:25,wavelengths_nm:[560],temperature_source:'display_default',wavelength_source:'display_default',assumed_fields:['temperature_c','wavelengths_nm']});
 assert.equal(r.temperatureSource,'display-default');assert.equal(r.wavelengthSource,'display-default');
});
test('missing metadata only defaults missing fields',()=>{
 const r=scope.resolveConditions({temperature_c:20});
 assert.equal(r.temperature,20);assert.equal(r.temperatureSource,'db');assert.equal(r.wavelengthSource,'display-default');
});
test('measured spectrum stays multiple with DB provenance',()=>{
 const r=scope.resolveConditions({temperature_c:20,wavelengths_nm:[450,546.074,656.2725]});
 assert.equal(r.kind,'multiple');assert.equal(r.wavelengthSource,'db');
});
test('initial ranges always contain imported current values',()=>{
 const context={settings:{},initiallyActive:new Set(['radius'])};
 vm.runInNewContext(extract('function config(', 'function activeDescriptors('),context);
 const c=context.config({key:'radius',min:16,max:160,obj:{radius:3},prop:'radius',available:true});
 assert.equal(c.min,3);assert.equal(c.max,160);
 const a=context.config({key:'a12',min:null,max:null,obj:{a12:null},prop:'a12',available:false});
 assert.equal(a.min,null);assert.equal(a.max,null);assert.equal(a.active,false);
});
