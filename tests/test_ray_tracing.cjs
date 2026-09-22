const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const Rays=require('../design/ray-tracing.js');

function surface(radius=0,aperture=6){return {radius,conic:0,aperture,a4:0,a6:0,a8:0,a10:0,a12:null};}
function system(front=0,rear=0){return {source:10,gaps:{gap12:3,gap23:3},lenses:[{material:'GLASS',type:'STANDARD',thickness:5,surfaces:[surface(front,4),surface(rear,6)]}],stop:{position_mode:'surface',surface_index:1,z_mm:null}};}
function triplet(){return {source:10,gaps:{gap12:3,gap23:4},lenses:[2,3,4].map(thickness=>({material:'GLASS',type:'STANDARD',thickness,surfaces:[surface(),surface()]}))};}
const n={GLASS:1.5};
function close(a,b,tolerance=1e-7){assert.ok(Math.abs(a-b)<=tolerance,`${a} != ${b} within ${tolerance}`);}
function finiteTree(value){if(typeof value==='number')assert.ok(Number.isFinite(value));else if(value&&typeof value==='object')Object.values(value).forEach(finiteTree);}
function imageRay(optics,height=1,angle=0,indices=n){return Rays.traceRay(optics,indices,{launch_height_mm:height,angle_rad:angle});}

test('plane slab obeys Snell and restores outgoing angle with correct lateral shift',()=>{
 const optics=system(),theta=.12;const ray=imageRay(optics,.2,theta);
 assert.equal(ray.status,'ok');close(ray.direction.z,-Math.cos(theta));close(ray.direction.y,Math.sin(theta));
 const internal=Math.asin(Math.sin(theta)/1.5),start=ray.points[0].z;
 const expected=.2+(start-5)*Math.tan(theta)+5*Math.tan(internal);
 close(ray.image_height_mm,expected);assert.notEqual(ray.image_height_mm,0);
 ray.interactions.forEach(event=>close(event.n_from*event.incidence_sine,event.n_to*event.refracted_sine,1e-10));
});

test('weak lens exact ray agrees with the reverse-direction paraxial transfer',()=>{
 const optics=system(10000,-10000);const exact=imageRay(optics,.04),para=Rays.traceParaxial(optics,n,{launch_height_mm:.04});
 assert.equal(exact.status,'ok');assert.equal(para.status,'ok');close(exact.image_height_mm,para.image_height_mm,1e-8);
 assert.ok(exact.direction.y<0);assert.ok(para.direction.y<0);
});

test('reversing curvature signs changes convergence to divergence',()=>{
 const convex=imageRay(system(100,-100),1),concave=imageRay(system(-100,100),1);
 assert.equal(convex.status,'ok');assert.equal(concave.status,'ok');
 assert.ok(convex.direction.y<0);assert.ok(concave.direction.y>0);
 assert.ok(convex.image_height_mm<1);assert.ok(concave.image_height_mm>1);
});

test('surface order and material transitions are rear to front',()=>{
 const optics=system();optics.lenses.push({material:'OTHER',type:'STANDARD',thickness:2,surfaces:[surface(),surface()]});
 const ray=imageRay(optics,1,0,{...n,OTHER:1.7});
 assert.deepEqual(ray.interactions.map(x=>x.surface_index),[4,3,2,1]);
 assert.deepEqual(ray.interactions.map(x=>[x.n_from,x.n_to]),[[1,1.7],[1.7,1],[1,1.5],[1.5,1]]);
});

test('both faces of an Even Asphere affect actual intersection/refraction',()=>{
 const base=system(100,-100);base.lenses[0].type='EVEN_ASPHERE';
 const baseline=imageRay(base,2).image_height_mm;
 const front=structuredClone(base);front.lenses[0].surfaces[0].a4=1e-4;
 const rear=structuredClone(base);rear.lenses[0].surfaces[1].a4=-1e-4;
 const both=structuredClone(front);both.lenses[0].surfaces[1].a4=-1e-4;
 for(const optics of [front,rear,both]){const ray=imageRay(optics,2);assert.equal(ray.status,'ok');assert.ok(Math.abs(ray.image_height_mm-baseline)>1e-4);}
 assert.notEqual(imageRay(both,2).image_height_mm,imageRay(front,2).image_height_mm);
});

test('Standard ignores dormant asphere coefficients without mutating them',()=>{
 const optics=system(100,-100),baseline=imageRay(optics,2).image_height_mm;
 optics.lenses[0].surfaces[0].a4=1e-4;optics.lenses[0].surfaces[1].a6=-1e-6;
 close(imageRay(optics,2).image_height_mm,baseline);assert.equal(optics.lenses[0].surfaces[0].a4,1e-4);
});

test('exact asphere intersection points lie on actual sag, not vertex planes',()=>{
 const optics=system(100,-100);optics.lenses[0].type='EVEN_ASPHERE';optics.lenses[0].surfaces[0].a4=1e-4;
 const ray=imageRay(optics,2);const front=ray.points.find(p=>p.surface_index===1),s=optics.lenses[0].surfaces[0];
 const c=1/s.radius,sag=c*front.y**2/(1+Math.sqrt(1-c*c*front.y**2))+s.a4*front.y**4;
 close(front.z,optics.source+sag,1e-8);assert.notEqual(front.z,optics.source);
});

test('marginal aiming reaches the true positive and negative stop edge symmetrically',()=>{
 const optics=system(100,-100),result=Rays.traceSection(optics,n);
 const rays=result.rays.filter(r=>r.kind==='marginal');assert.equal(rays.length,2);
 assert.ok(rays.every(r=>r.status==='ok'));close(rays[0].stop_height_mm,-4,1e-6);close(rays[1].stop_height_mm,4,1e-6);
 close(rays[0].launch_height_mm,-rays[1].launch_height_mm,1e-6);
 assert.ok(Math.abs(rays[1].launch_height_mm)>4);
 close(rays[1].stop_point.z,result.stop.edge_z_mm,1e-6);
 assert.equal(result.image_z_mm,0);assert.ok(result.rays.some(r=>r.kind==='chief'));
});

test('meniscus stop edge beyond the rear vertex still aims after the rear interface',()=>{
 const optics=system(10,10);optics.lenses[0].thickness=.5;
 const result=Rays.traceSection(optics,n);
 assert.ok(result.stop.edge_z_mm>optics.source+optics.lenses[0].thickness);
 const marginal=result.rays.filter(r=>r.kind==='marginal');
 assert.ok(marginal.every(r=>r.status==='ok'));
 marginal.forEach(ray=>close(ray.stop_height_mm,ray.target_stop_height_mm,1e-6));
});

test('absolute stop in image-side air is an actual aiming plane',()=>{
 const optics=system(-100,100);optics.stop={position_mode:'absolute',surface_index:1,z_mm:5};
 const result=Rays.traceSection(optics,n),marginal=result.rays.filter(r=>r.kind==='marginal');
 assert.ok(marginal.every(r=>r.status==='ok'));
 marginal.forEach(r=>{close(r.stop_point.z,5);close(Math.abs(r.stop_point.y),4,1e-6);});
});

test('image-side stop cannot demand an edge blocked by a converging front aperture',()=>{
 const optics=system(100,-100);optics.stop={position_mode:'absolute',surface_index:1,z_mm:5};
 const result=Rays.traceSection(optics,n);
 assert.ok(result.rays.filter(r=>r.kind==='marginal').every(r=>r.status==='unreachable'));
 assert.ok(result.diagnostics.some(d=>d.code==='STOP_UNREACHABLE'));
});

test('absolute stop on object side extends the launch plane and keeps apertures',()=>{
 const optics=system(100,-100);optics.stop={position_mode:'absolute',surface_index:1,z_mm:40};
 const result=Rays.traceSection(optics,n);assert.ok(result.start_z_mm>40);
 result.rays.filter(r=>r.kind==='marginal').forEach(r=>{close(r.launch_height_mm,r.target_stop_height_mm);close(r.stop_point.z,40);});
});

test('a correctly aimed object-side marginal can still be vignetted afterwards',()=>{
 const optics=system(-100,100);optics.stop={position_mode:'absolute',surface_index:1,z_mm:40};
 const result=Rays.traceSection(optics,n),marginal=result.rays.filter(r=>r.kind==='marginal');
 assert.ok(marginal.every(r=>r.status==='clipped'));
 assert.ok(marginal.every(r=>r.image_height_mm===undefined));
 marginal.forEach(r=>close(r.stop_height_mm,r.target_stop_height_mm));
 assert.ok(result.diagnostics.some(d=>d.code==='MARGINAL_VIGNETTED'));
 assert.equal(result.rays.filter(r=>r.kind==='reference').length,6);
});

test('small clear apertures cannot turn an axis ray into a falsely valid marginal',()=>{
 const optics=system();optics.lenses[0].surfaces.forEach(s=>s.aperture=1e-8);
 const marginal=Rays.traceSection(optics,n).rays.filter(r=>r.kind==='marginal');
 marginal.forEach(r=>{assert.equal(r.status,'ok');close(Math.abs(r.stop_height_mm),1e-8,1e-14);});
});

test('index-matched asphere surfaces do not bend a straight ray',()=>{
 const optics=system(100,-100);optics.lenses[0].type='EVEN_ASPHERE';
 optics.lenses[0].surfaces[0].a4=1e-4;optics.lenses[0].surfaces[1].a6=-1e-6;
 const ray=imageRay(optics,1,.05,{GLASS:1});assert.equal(ray.status,'ok');
 close(ray.image_height_mm,1+ray.points[0].z*Math.tan(.05));
 close(ray.direction.y,Math.sin(.05));
});

test('unreachable stop does not relabel a vignetted entrance edge as marginal',()=>{
 const optics=system();optics.lenses[0].surfaces[0].aperture=6;optics.lenses[0].surfaces[1].aperture=2;
 const result=Rays.traceSection(optics,n),marginal=result.rays.filter(r=>r.kind==='marginal');
 assert.ok(marginal.every(r=>r.status==='unreachable'));assert.ok(marginal.every(r=>r.image_height_mm===undefined));
 assert.ok(result.diagnostics.some(d=>d.code==='STOP_UNREACHABLE'));
 assert.equal(result.rays.filter(r=>r.kind==='reference').length,6);
 assert.ok(result.rays.filter(r=>r.kind==='reference').some(r=>r.status==='ok'));
});

test('absolute stop inside glass or across a curved surface is rejected',()=>{
 for(const z of [12,10.04]){const optics=system(100,-100);optics.stop={position_mode:'absolute',surface_index:1,z_mm:z};
  const result=Rays.traceSection(optics,n);assert.equal(result.status,'invalid_stop_position');assert.equal(result.rays.length,0);}
});

test('ray beyond a clear aperture stops with clipped status and no image result',()=>{
 const ray=imageRay(system(),7);assert.equal(ray.status,'clipped');assert.equal(ray.image_height_mm,undefined);finiteTree(ray);
});

test('missing or invalid refractive index produces no fabricated ray path',()=>{
 for(const indices of [{},{GLASS:NaN},{GLASS:0}]){const result=Rays.traceSection(system(),indices);assert.equal(result.status,'missing_index');assert.equal(result.rays.length,0);finiteTree(result);}
});

test('nonreal surfaces, crossing lens faces and nonfinite geometry fail finitely',()=>{
 const cases=[];
 let x=system(1,-1);cases.push(x);
 x=system(8,-8);x.lenses[0].thickness=.01;cases.push(x);
 x=system();x.source=NaN;cases.push(x);
 x=system();x.lenses[0].thickness=-1;cases.push(x);
 x=system();x.lenses[0].type='EVEN_ASPHERE';x.lenses[0].surfaces[0].a4=Infinity;cases.push(x);
 for(const optics of cases){const result=Rays.traceSection(optics,n);assert.equal(result.status,'invalid_geometry');finiteTree(result);}
});

test('invalid standalone launch values return finite diagnostics',()=>{
 for(const value of [NaN,Infinity]){
  const exact=Rays.traceRay(system(),n,{launch_height_mm:value}),para=Rays.traceParaxial(system(),n,{launch_height_mm:value});
  for(const ray of [exact,para]){assert.equal(ray.status,'invalid_geometry');finiteTree(ray);}
 }
});

test('total internal reflection is reported, not replaced with a focusing line',()=>{
 const optics=system();optics.lenses[0].surfaces.forEach(s=>s.aperture=100);
 const ray=imageRay(optics,0,.7,{GLASS:.5});assert.equal(ray.status,'tir');assert.equal(ray.image_height_mm,undefined);finiteTree(ray);
});

test('parallel plane-slab rays remain offset at image z=0 rather than forced to focus',()=>{
 const result=Rays.traceSection(system(),n);
 for(const r of result.rays.filter(r=>r.status==='ok'))close(r.image_height_mm,r.launch_height_mm);
 assert.ok(Math.abs(Rays.traceParaxial(system(),n,{launch_height_mm:.1}).image_height_mm)>0);
});

test('default stop binds to the farthest lens outer face and returns a true 0F chief',()=>{
 const optics=triplet();optics.lenses[2].surfaces[1].aperture=2;
 const result=Rays.traceSection(optics,n);
 assert.equal(result.stop.surface_index,6);assert.equal(result.stop.z_mm,26);assert.equal(result.stop.semi_diameter_mm,2);
 const chiefs=result.rays.filter(ray=>ray.kind==='chief');assert.equal(chiefs.length,1);
 const chief=chiefs[0];assert.equal(chief.method,'meridional_snell');assert.equal(chief.status,'ok');
 assert.equal(chief.target_stop_height_mm,0);assert.equal(chief.stop_height_mm,0);assert.equal(chief.image_height_mm,0);
 assert.ok(chief.points.every(point=>point.y===0));assert.equal(chief.interactions.length,6);
 assert.ok(result.rays.every(ray=>!['axis','paraxial'].includes(ray.kind)));
 const marginal=result.rays.filter(ray=>ray.kind==='marginal');assert.equal(marginal.length,2);
 marginal.forEach(ray=>{assert.equal(ray.status,'ok');close(Math.abs(ray.stop_height_mm),2);});
});

test('default stop recomputes its vertex, CSD and sag after parameter changes',()=>{
 const optics=triplet();optics.lenses[2].surfaces[1].aperture=2;
 const first=Rays.traceSection(optics,n).stop;
 optics.source+=2;optics.gaps.gap12+=1;optics.gaps.gap23+=.5;
 optics.lenses[0].thickness+=.3;optics.lenses[1].thickness+=.4;optics.lenses[2].thickness+=.5;
 optics.lenses[2].type='EVEN_ASPHERE';const outer=optics.lenses[2].surfaces[1];
 outer.aperture=2.5;outer.radius=100;outer.a4=1e-5;
 const result=Rays.traceSection(optics,n),stop=result.stop;
 close(stop.z_mm,first.z_mm+4.7);assert.equal(stop.semi_diameter_mm,2.5);
 const c=.01,y=2.5;close(stop.edge_z_mm,stop.z_mm+c*y*y/(1+Math.sqrt(1-c*c*y*y))+1e-5*y**4);
 assert.equal(stop.surface_index,6);
});

test('an explicit old surface-1 stop retains its binding',()=>{
 const optics=triplet();optics.stop={position_mode:'surface',surface_index:1,z_mm:null};
 optics.lenses[0].surfaces[0].aperture=1.5;optics.lenses[2].surfaces[1].aperture=4;
 const result=Rays.traceSection(optics,n);
 assert.equal(result.stop.surface_index,1);assert.equal(result.stop.z_mm,10);assert.equal(result.stop.semi_diameter_mm,1.5);
 result.rays.filter(ray=>ray.kind==='marginal').forEach(ray=>{assert.equal(ray.status,'ok');close(Math.abs(ray.stop_height_mm),1.5);});
});

test('surface-3 edge aiming includes preceding interfaces and records the selected stop',()=>{
 const optics=triplet();optics.stop={position_mode:'surface',surface_index:3,z_mm:null};
 optics.lenses[1].surfaces=[surface(100,2),surface(-100,6)];
 const result=Rays.traceSection(optics,n);
 assert.equal(result.stop.surface_index,3);assert.equal(result.stop.z_mm,15);
 result.rays.filter(ray=>ray.kind==='marginal').forEach(ray=>{
  assert.equal(ray.status,'ok');close(Math.abs(ray.stop_height_mm),2,1e-6);
  const stop=ray.points.find(point=>point.stop);assert.equal(stop.surface_index,3);
  close(stop.z,result.stop.edge_z_mm,1e-6);assert.deepEqual(ray.interactions.map(event=>event.surface_index),[6,5,4,3,2,1]);
 });
});

test('every explicit surface index is supported and invalid bindings are rejected',()=>{
 for(let selected=1;selected<=6;selected++){
  const optics=triplet();optics.stop={position_mode:'surface',surface_index:selected,z_mm:null};
  optics.lenses[Math.floor((selected-1)/2)].surfaces[(selected-1)%2].aperture=1;
  const result=Rays.traceSection(optics,n);assert.equal(result.stop.surface_index,selected);
  const chief=result.rays.find(ray=>ray.kind==='chief');assert.equal(chief.points.find(point=>point.stop).surface_index,selected);
  assert.ok(result.rays.filter(ray=>ray.kind==='marginal').every(ray=>ray.status==='ok'));
 }
 for(const selected of [0,7,1.5,'1']){
  const optics=triplet();optics.stop={position_mode:'surface',surface_index:selected,z_mm:null};
  assert.equal(Rays.traceSection(optics,n).status,'invalid_stop_position');
 }
});

test('absolute stop uses its bound surface CSD while its axial position stays custom',()=>{
 const optics=triplet();optics.stop={position_mode:'absolute',surface_index:6,z_mm:40};
 optics.lenses[2].surfaces[1].aperture=2;const before=JSON.stringify(optics);
 const result=Rays.traceSection(optics,n);assert.equal(result.stop.z_mm,40);assert.equal(result.stop.semi_diameter_mm,2);
 assert.equal(JSON.stringify(optics),before);
 optics.source+=1;optics.lenses[2].surfaces[1].aperture=2.5;
 const changed=Rays.traceSection(optics,n);assert.equal(changed.stop.z_mm,40);assert.equal(changed.stop.semi_diameter_mm,2.5);
});

test('surface mode with no explicit binding defaults without mutating caller data',()=>{
 const optics=triplet();optics.stop={position_mode:'surface',z_mm:null};const before=JSON.stringify(optics);
 const result=Rays.traceSection(optics,n);assert.equal(result.stop.surface_index,6);assert.equal(JSON.stringify(optics),before);
});

test('input state remains unchanged and module also exports a browser global',()=>{
 const optics=system(),before=JSON.stringify(optics);Rays.traceSection(optics,n);assert.equal(JSON.stringify(optics),before);
 const context={};vm.runInNewContext(fs.readFileSync('design/ray-tracing.js','utf8'),context);
 assert.equal(typeof context.OpticsRays.traceSection,'function');
});
