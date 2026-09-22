const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('design/optics-workspace-concept.html','utf8');
const start=source.indexOf('function resolveStop('),end=source.indexOf('let sectionZoom=',start);
assert.ok(start>=0&&end>start,'stop position policy must exist');
const policy={};vm.runInNewContext(source.slice(start,end),policy);
function optics(){return {source:10,gaps:{gap12:2,gap23:3},lenses:[4,5,6].map((thickness,i)=>({thickness,surfaces:[{aperture:9+i},{aperture:11+i}]})),stop:{position_mode:'surface',surface_index:6,z_mm:null}}}
test('default stop follows the farthest outer face and its clear semi-diameter',()=>{
 const s=optics();assert.equal(policy.resolveStop(s).z_mm,30);assert.equal(policy.resolveStop(s).semi_diameter_mm,13);
 s.source=12;s.lenses[0].thickness=5;s.gaps.gap23=4;s.lenses[2].surfaces[1].aperture=14;
 assert.equal(policy.resolveStop(s).z_mm,34);assert.equal(policy.resolveStop(s).semi_diameter_mm,14);
 assert.equal(policy.resolveStop(s).surface_index,6);
});
test('dragging detaches only axial position and keeps the lens prescription unchanged',()=>{
 const s=optics(),before=JSON.stringify(s);s.stop=policy.moveStop(18.2,6);
 assert.equal(policy.resolveStop(s).z_mm,18.2);s.source=11;
 assert.equal(policy.resolveStop(s).z_mm,18.2);assert.equal(s.lenses[2].surfaces[1].aperture,13);
 assert.equal(JSON.parse(before).source,10);
});
test('drag conversion respects actual section zoom and clamps at the origin',()=>{
 assert.equal(policy.stopZFromDrag(10,30,6),15);
 assert.equal(policy.stopZFromDrag(10,30,12),12.5);
 assert.equal(policy.stopZFromDrag(10,-100,6),0);
});
test('nonfinite positions and invalid scales are rejected',()=>{
 for(const z of [NaN,Infinity,-1,'8'])assert.throws(()=>policy.moveStop(z));
 for(const scale of [0,-1,NaN])assert.throws(()=>policy.stopZFromDrag(10,5,scale));
});
test('a workspace without stop uses the last outer face',()=>{
 const s=optics();delete s.stop;assert.equal(policy.resolveStop(s).z_mm,30);assert.equal(policy.resolveStop(s).surface_index,6);
});
test('explicit saved surface attachment is preserved',()=>{
 const s=optics();s.stop.surface_index=1;assert.equal(policy.resolveStop(s).z_mm,10);assert.equal(policy.resolveStop(s).semi_diameter_mm,9);
 s.stop.surface_index=3;assert.equal(policy.resolveStop(s).z_mm,16);assert.equal(policy.resolveStop(s).semi_diameter_mm,10);
});
test('manual movement retains the attached aperture source',()=>{
 const s=optics();s.stop=policy.moveStop(40,3);assert.equal(policy.resolveStop(s).surface_index,3);assert.equal(policy.resolveStop(s).semi_diameter_mm,10);
});
