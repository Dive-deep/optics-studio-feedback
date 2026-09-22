/* Validate an entire UI snapshot before mutating the live workspace. */
(function () {
  "use strict";
  const reserved = new Set(["__proto__", "constructor", "prototype"]);
  function fail(label) { throw new Error(label + " 설정이 올바르지 않습니다."); }
  function object(value,label) {
    if (!value || typeof value !== "object" || Array.isArray(value)) fail(label);
    if (Object.keys(value).some(key => reserved.has(key))) fail(label);
    return value;
  }
  function number(value,label) { if (!Number.isFinite(value)) fail(label); return value; }
  function positive(value,label,integer=false) {
    number(value,label);
    if (value <= 0 || integer && !Number.isInteger(value)) fail(label);
    return value;
  }
  function text(value,label,max=200000) { if(typeof value!=="string"||value.length>max)fail(label);return value; }
  function bool(value,label) { if(typeof value!=="boolean")fail(label);return value; }
  function vector(value,label) {
    if(!Array.isArray(value)||value.length!==3||!value.every(Number.isFinite))fail(label);
    return value.slice();
  }
  window.validateOpticsWorkspaceSnapshot = function (input) {
    const s=object(input,"Workspace");
    if(s.ui_version!==1)fail("Workspace 버전");
    const raw=object(s.optics,"광학계"),values=Object.create(null);
    if(!Array.isArray(raw.lenses)||raw.lenses.length!==3)fail("렌즈 수");
    const lenses=raw.lenses.map((item,i)=>{
      const l=object(item,"렌즈");
      if(!["STANDARD","EVEN_ASPHERE"].includes(l.type)||!Array.isArray(l.surfaces)||l.surfaces.length!==2)fail("표면 종류");
      const thickness=number(l.thickness,"두께");values["L"+i+"thickness"]=thickness;
      return {material:text(l.material,"재질",256),type:l.type,thickness,
        surfaces:l.surfaces.map((item,j)=>{
          const p=object(item,"표면"),out={};
          for(const key of ["radius","conic","aperture","a4","a6","a8","a10"]){
            out[key]=number(p[key],key);values["L"+i+"S"+j+key]=out[key];
          }
          if(p.a12!==null)fail("A12 공란");
          out.a12=null;values["L"+i+"S"+j+"a12"]=null;
          return out;
        })
      };
    });
    const gaps=object(raw.gaps,"간격");
    const source=number(raw.source,"광원 거리"),gap12=number(gaps.gap12,"L1-L2 간격"),gap23=number(gaps.gap23,"L2-L3 간격");
    Object.assign(values,{source,gap12,gap23});
    const surfaceCount=lenses.length*2;
    const stopRaw=raw.stop===undefined?{position_mode:"surface",surface_index:surfaceCount,z_mm:null}:object(raw.stop,"조리개");
    if(!["surface","absolute"].includes(stopRaw.position_mode)||!Number.isInteger(stopRaw.surface_index)
      ||stopRaw.surface_index<1||stopRaw.surface_index>surfaceCount)fail("조리개 위치");
    let stopZ=null;
    if(stopRaw.position_mode==="surface"){
      if(stopRaw.z_mm!==null)fail("조리개 면 기준 위치");
    }else{
      stopZ=number(stopRaw.z_mm,"조리개 절대 위치");
      if(stopZ<0)fail("조리개 절대 위치");
    }
    // Preserve explicit saved surface bindings. Diameter follows that
    // surface's CSD rather than becoming an independent persisted setting.
    const stop={position_mode:stopRaw.position_mode,surface_index:stopRaw.surface_index,z_mm:stopZ};
    if(!Number.isInteger(raw.lens)||raw.lens<0||raw.lens>2||![0,1].includes(raw.side)||!["studio","analysis"].includes(raw.layout))fail("선택 화면");
    const rv=raw.ray_visibility===undefined?{chief:true,marginal:true}:object(raw.ray_visibility,"광선 표시");
    const hasChief=Object.hasOwn(rv,"chief"),hasLegacyParaxial=Object.hasOwn(rv,"paraxial");
    if(!hasChief&&!hasLegacyParaxial)fail("광선 표시");
    if(hasLegacyParaxial)bool(rv.paraxial,"이전 Paraxial 표시");
    // A disabled paraxial approximation was not a choice to hide chief rays.
    // Validate the legacy field, then enable the new display independently.
    const ray_visibility={chief:hasChief?bool(rv.chief,"Chief 표시"):true,marginal:bool(rv.marginal,"Marginal 표시")};
    const optics={lens:raw.lens,side:raw.side,section:bool(raw.section,"단면"),layout:raw.layout,ray_visibility,
      coverageExample:bool(raw.coverageExample,"영역 표시"),source,gaps:{gap12,gap23},lenses,stop};
    const parameters=Object.create(null);
    for(const [key,item] of Object.entries(object(s.parameters,"변수"))){
      if(!Object.hasOwn(values,key))fail("변수 ID");
      const p=object(item,"변수"),active=bool(p.active,"활성 상태");
      if(values[key]===null){
        if(active||p.min!==null||p.max!==null)fail("A12 공란");
        parameters[key]={active:false,min:null,max:null};
      }else{
        const min=number(p.min,"최소"),max=number(p.max,"최대");
        if(min>=max||values[key]<min||values[key]>max)fail("변수 범위");
        parameters[key]={active,min,max};
      }
    }
    const t=object(s.training||{learning_rate:.001,epochs:100,gpu_location:"local",new_version:"new-model"},"학습");
    if(!["local","server"].includes(t.gpu_location))fail("Compute");
    const training={learning_rate:positive(t.learning_rate,"Learning rate"),epochs:positive(t.epochs,"Epochs",true),
      gpu_location:t.gpu_location,new_version:text(t.new_version,"모델 버전",256)};
    const a=object(s.automation||{hours:24,iterations:1000,window:100,improvement:.5},"자동 설계");
    const automation={hours:positive(a.hours,"최대 시간"),iterations:positive(a.iterations,"최대 반복",true),
      window:positive(a.window,"개선 검사 구간",true),improvement:number(a.improvement,"개선율")};
    if(automation.improvement<0)fail("개선율");
    const chart_views=Object.create(null);
    for(const [key,item] of Object.entries(object(s.chart_views||{},"그래프"))){
      if(!["mtf","spot"].includes(key))fail("그래프 ID");
      const c=object(item,"그래프");
      const k=number(c.k,"그래프 확대");
      if(k<1||k>12)fail("그래프 확대");
      chart_views[key]={k,x:number(c.x,"그래프 이동"),y:number(c.y,"그래프 이동")};
    }
    let camera=null;
    if(s.camera!==null&&s.camera!==undefined){
      const c=object(s.camera,"카메라"),fov=number(c.fov,"카메라 FOV");
      if(fov<=1||fov>=179)fail("카메라 FOV");
      camera={position:vector(c.position,"카메라 위치"),target:vector(c.target,"카메라 중심"),zoom:positive(c.zoom,"카메라 확대"),fov};
    }
    const section_zoom=s.section_zoom===undefined?1:number(s.section_zoom,"단면 확대");
    if(section_zoom<.5||section_zoom>3)fail("단면 확대");
    const views=["workspace","configure","conditions","targets","candidates","model","update","auto","llm","mtf","spot","sim","project"];
    if(!views.includes(s.view))fail("화면");
    const reference_data=JSON.parse(JSON.stringify(object(s.reference_data,"참조 데이터")));
    let pareto_view;
    if(s.pareto_view!==undefined){
      const p=object(s.pareto_view,"Pareto");
      if(!["eligible","exploratory"].includes(p.mode)||!["pair","full"].includes(p.projection)||
         !Array.isArray(p.dimensions)||p.dimensions.length!==2||new Set(p.dimensions).size!==2||
         p.dimensions.some(k=>!["mtf","spot","horizontal_fov"].includes(k)))fail("Pareto 표시");
      const optional=(value,label)=>value==null?null:text(value,label,256);
      pareto_view={cohort_key:optional(p.cohort_key,"분석 조건"),source_kind:optional(p.source_kind,"결과 출처"),
        mode:p.mode,dimensions:p.dimensions.slice(),projection:p.projection,show_line:bool(p.show_line,"Pareto 연결선"),
        ...(p.focus_front===undefined?{}:{focus_front:bool(p.focus_front,"Pareto 확대")}),
        selected_id:optional(p.selected_id,"선택 후보")};
    }
    return {ui_version:1,optics,parameters,training,automation,chart_views,camera,section_zoom,
      view:["sim","project"].includes(s.view)?"workspace":s.view,llm_draft:text(s.llm_draft||"","LLM 초안"),reference_data,
      ...(pareto_view?{pareto_view}: {})};
  };
})();
