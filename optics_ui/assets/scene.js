
    import * as THREE from './vendor/three/three.module.js';
    import {OrbitControls} from './vendor/three/OrbitControls.js';
    const root=document.getElementById('optics-review'),canvas=root.querySelector('#o-canvas'),host=root.querySelector('#o-view'),state=root.__opticsState;
    try {
      const context=canvas.getContext('webgl2',{antialias:true,alpha:true});
      if(!context){root.__setWebGLUnavailable('webgl2-unavailable')}
      else {
      const renderer=new THREE.WebGLRenderer({canvas:canvas,context:context,antialias:true,alpha:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor(0x000000,0);
      const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(34,1,.1,500);camera.position.set(67,34,63);
      const controls=new OrbitControls(camera,canvas);controls.target.set(24,0,0);controls.enableDamping=false;controls.minDistance=18;controls.maxDistance=200;
      scene.add(new THREE.HemisphereLight(0xffffff,0x496078,2.4));const light=new THREE.DirectionalLight(0xffffff,3.5);light.position.set(-20,40,60);scene.add(light);
      const group=new THREE.Group();scene.add(group);
      function color(token){const p=document.createElement('span');p.style.color='var('+token+')';root.appendChild(p);const c=getComputedStyle(p).color;p.remove();return new THREE.Color(c)}
      function cleanup(){while(group.children.length){const o=group.children[0];o.traverse(function(n){if(n.geometry)n.geometry.dispose();if(n.material){if(Array.isArray(n.material))n.material.forEach(function(m){m.dispose()});else n.material.dispose()}});group.remove(o)}}
      function rebuild(){cleanup();const pos=root.__zPositions();let valid=true;state.lenses.forEach(function(l,index){const a=Math.min(l.surfaces[0].aperture,l.surfaces[1].aperture),profile=[],count=48;for(let j=0;j<=count;j++){const r=a*j/count,z=pos[index][0]+root.__sag(l.surfaces[0],r);if(!Number.isFinite(z)){valid=false;return}profile.push(new THREE.Vector2(r,z))}for(let j=count;j>=0;j--){const r=a*j/count,z=pos[index][1]+root.__sag(l.surfaces[1],r);if(!Number.isFinite(z)){valid=false;return}profile.push(new THREE.Vector2(r,z))}if(profile.length!==2*(count+1))return;const geo=new THREE.LatheGeometry(profile,96);geo.rotateZ(-Math.PI/2);const mat=new THREE.MeshPhysicalMaterial({color:color('--o-glass'),metalness:0,roughness:.18,transparent:true,opacity:.48,side:THREE.DoubleSide,depthWrite:false});group.add(new THREE.Mesh(geo,mat));[0,1].forEach(function(side){const s=l.surfaces[side],r=s.aperture,z=pos[index][side]+root.__sag(s,r),pts=[];if(!Number.isFinite(z))return;for(let i=0;i<=100;i++){const t=i/100*Math.PI*2;pts.push(new THREE.Vector3(z,r*Math.cos(t),r*Math.sin(t)))}group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineBasicMaterial({color:color(index===state.lens?'--o-blue':'--o-teal'),transparent:true,opacity:.6})))})});
        const plane=new THREE.Mesh(new THREE.PlaneGeometry(26,20),new THREE.MeshBasicMaterial({color:color('--o-teal'),transparent:true,opacity:.07,side:THREE.DoubleSide}));plane.rotation.y=Math.PI/2;group.add(plane);
        const outline=new THREE.LineSegments(new THREE.EdgesGeometry(plane.geometry),new THREE.LineBasicMaterial({color:color('--o-teal'),transparent:true,opacity:.5}));outline.rotation.y=Math.PI/2;group.add(outline);
        if(!state.section)root.querySelector('#o-view-note').textContent=valid?'Image plane · reference at (0,0)':'형상을 만들 수 없는 파라미터';render();
      }
      function render(){if(root.dataset.webgl==='failed'||state.section||!host.clientWidth)return;renderer.setSize(host.clientWidth,host.clientHeight,false);camera.aspect=host.clientWidth/host.clientHeight;camera.updateProjectionMatrix();renderer.render(scene,camera)}
      root.__getCameraSnapshot=function(){return {position:camera.position.toArray(),target:controls.target.toArray(),zoom:camera.zoom,fov:camera.fov}};root.__restoreCamera=function(saved){if(!saved||!Array.isArray(saved.position)||saved.position.length!==3||!saved.position.every(Number.isFinite)||!Array.isArray(saved.target)||saved.target.length!==3||!saved.target.every(Number.isFinite))return;camera.position.fromArray(saved.position);controls.target.fromArray(saved.target);if(Number.isFinite(saved.zoom)&&saved.zoom>0)camera.zoom=saved.zoom;if(Number.isFinite(saved.fov)&&saved.fov>1&&saved.fov<179)camera.fov=saved.fov;controls.update();render()};if(root.__pendingCamera)root.__restoreCamera(root.__pendingCamera);
      controls.addEventListener('change',render);root.addEventListener('optics-update',rebuild);new ResizeObserver(render).observe(host);matchMedia('(prefers-color-scheme: dark)').addEventListener('change',rebuild);rebuild();root.dataset.webgl='ready';root.__syncViewerMode();
      canvas.addEventListener('webglcontextlost',function(event){event.preventDefault();root.__setWebGLUnavailable('context-lost')});
      }
    }catch(e){root.__setWebGLUnavailable('renderer-error');console.error('3D viewer initialization failed',e)}
  