/* DB candidate exploration. All evaluation is delegated to OpticsPareto.
   This view never predicts, runs simulations, or changes the target profile. */
(function(global){
  'use strict';
  global.createOpticsParetoView=function(hooks){
    const root=hooks.root, $=id=>root.querySelector('#'+id);
    const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const num=(v,n=3)=>Number.isFinite(v)?v.toFixed(n):'—';
    const copy=v=>JSON.parse(JSON.stringify(v));
    const defaults=()=>({cohort_key:null,source_kind:null,mode:'eligible',dimensions:['spot','horizontal_fov'],projection:'pair',show_line:true,focus_front:false,selected_id:null});
    let view=defaults(), cache={}, selections={}, undo=null, busy=false, lastReference=null;
    const sourceName=k=>({synthetic:'합성 DB',zemax:'Zemax 결과',db:'DB 결과',predicted:'모델 예측'}[k]||k||'출처 미확인');
    const axisName=k=>({spot:'Spot 목표편차 (%) ↓',horizontal_fov:'FOV 목표편차 (%) ↓',mtf:'MTF 최악 충족률 (%) ↑'}[k]);
    const display=(cost,key)=>key==='mtf'?(1-cost)*100:cost*100;
    const editKey=()=>hooks.editKey();
    const canUndo=()=>undo&&undo.reference===lastReference&&undo.appliedKey===editKey();
    function context(){return hooks.getContext()}
    function profile(){return context().target?.profile||hooks.fallbackProfile}
    function evaluated(){
      const c=context(),p=profile();
      if(cache.data!==c.candidateData||cache.profile!==p){
        cache={data:c.candidateData,profile:p,value:global.OpticsPareto.evaluateCases(c.candidateData?.cases||[],p)};
        selections={};
      }
      return cache.value;
    }
    function selectedCohort(){
      const e=evaluated(), groups=e.cohorts||[];
      let group=groups.find(g=>g.cohort_key===view.cohort_key&&g.source_kind===view.source_kind);
      if(!group){
        const current=e.rows.find(r=>r.id===hooks.getCurrentId()&&r.evaluation.comparison_ready);
        group=groups.find(g=>g.cohort_key===current?.cohort_key&&g.source_kind===current?.source_kind)||groups[0];
        view.cohort_key=group?.cohort_key||null;view.source_kind=group?.source_kind||null;
      }
      return group;
    }
    function result(){
      selectedCohort();
      const e=evaluated(),key=JSON.stringify([view.cohort_key,view.source_kind,view.mode,view.dimensions,view.projection]);
      if(selections.key!==key||selections.valueOf!==e)
        selections={key,valueOf:e,value:global.OpticsPareto.explore(e,view)};
      return selections.value;
    }
    function message(){
      const c=context();
      if(!c.references?.database_path)return '리포트와 DB를 연결하면 Pareto 후보를 비교할 수 있습니다.';
      if(c.candidateStatus==='loading')return 'DB 성능과 분석 조건을 읽고 있습니다…';
      if(c.candidateStatus==='error')return c.candidateError?.message||'후보 데이터를 읽을 수 없습니다.';
      if(c.candidateStatus!=='ready')return 'DB 후보 데이터를 불러오세요.';
      const e=evaluated();
      if(e.status!=='ready')return e.errors.map(x=>x.message).join(' / ');
      if(!e.cohorts.length)return '비교 가능한 분석 조건·성능을 갖춘 케이스가 없습니다.';
      if(!result().rows.length)return '이 분석 조건에서 합격·5% 허용 후보가 없습니다.';
      return '';
    }
    function mini(){
      const el=$('o-pareto-summary');if(!el)return;
      const r=result(),m=message();
      el.textContent=m||sourceName(r.source_kind)+' · 대상 '+r.counts.shown+' · '+r.pareto_ids.length+' Pareto'+(view.mode==='exploratory'?' · 미달 포함':'')+(view.focus_front?' · Pareto 주변 확대':'');
      $('o-pareto-undo').hidden=!undo;
      $('o-pareto-undo').disabled=busy||!canUndo();
    }
    function refresh(){
      const c=context(),key=JSON.stringify([c.references?.report_path,c.references?.database_path]);
      if(lastReference!==null&&lastReference!==key)undo=null;
      lastReference=key;
      if(c.candidateStatus!=='ready'){cache={};selections={}}
      mini();
      if(hooks.isActive())open();else draw();
    }
    function option(value,label,current,disabled=false){
      return '<option value="'+esc(value)+'" '+(value===current?'selected ':'')+(disabled?'disabled':'')+'>'+esc(label)+'</option>';
    }
    function open(){
      const e=evaluated(),r=result(),c=context(),groups=e.cohorts;
      const groupOptions=groups.map((g,i)=>{
        const row=e.rows.find(x=>x.cohort_key===g.cohort_key&&x.source_kind===g.source_kind);
        return option(String(i),sourceName(g.source_kind)+' · '+num(row?.conditions?.temperature_c,1)+'°C · 조건 '+(i+1)+' · '+g.count+' cases',
          g.cohort_key===view.cohort_key&&g.source_kind===view.source_kind?String(i):'');
      }).join('');
      const axes=['spot','horizontal_fov','mtf'];
      const targetLabel=c.target?'Loaded target JSON · Read only':'임시 목표 · UI example · Read only';
      const best=e.rows.find(x=>x.id===r.best_id&&x.cohort_key===r.cohort_key&&x.source_kind===r.source_kind);
      let html='<div class="o-small">'+targetLabel+'</div>'+
        '<label class="o-field"><span>Candidate set</span><select id="o-pareto-mode">'+option('eligible','합격 + 상대 5% 허용',view.mode)+option('exploratory','미달 포함 탐색 (합격 아님)',view.mode)+'</select></label>'+
        '<details id="o-pareto-settings"><summary class="o-small">비교 조건 · 성능 축 · 2D / 3목적 설정</summary><div class="o-pareto-controls">'+
        '<label class="o-field"><span>DB source / analysis conditions</span><select id="o-pareto-cohort" '+(!groups.length?'disabled':'')+'>'+groupOptions+'<option disabled>Model prediction · Backend not connected</option></select></label>'+
        '<label class="o-field"><span>X axis</span><select id="o-pareto-x">'+axes.map(k=>option(k,axisName(k),view.dimensions[0],k===view.dimensions[1])).join('')+'</select></label>'+
        '<label class="o-field"><span>Y axis</span><select id="o-pareto-y">'+axes.map(k=>option(k,axisName(k),view.dimensions[1],k===view.dimensions[0])).join('')+'</select></label>'+
        '<label class="o-field"><span>Pareto definition</span><select id="o-pareto-projection">'+option('pair','선택한 2개 목적',view.projection)+option('full','전체 3목적 후보의 2D 투영',view.projection)+'</select></label>'+
        '<div class="o-field"><span>View</span><label class="o-small"><input id="o-pareto-line" type="checkbox" '+(view.show_line?'checked ':'')+(view.projection==='full'?'disabled':'')+'> 후보 연결 가이드</label></div></div></details>'+
        '<div class="o-demo-list"><button id="o-pareto-refresh" '+(!c.references?.database_path||c.candidateStatus==='loading'?'disabled':'')+'>Refresh DB</button>'+
        '<button id="o-pareto-focus" '+(!r.pareto_ids.length?'disabled':'')+'>'+(view.focus_front?'전체 분포 보기':'Pareto 주변 확대')+'</button>'+
        '<button id="o-pareto-apply-best" '+(!best||busy?'disabled':'')+'>Apply DB best'+(best?' · '+esc(best.id):'')+'</button>'+
        '<button id="o-pareto-undo-panel" '+(!canUndo()||busy?'disabled':'')+'>적용 되돌리기</button></div>'+
        '<div class="o-callout" id="o-pareto-status">'+esc(message()||sourceName(r.source_kind)+' · 표시 '+r.counts.shown+' / 비교 가능 '+r.counts.comparable+' · 전체 제외 '+r.counts.excluded)+
        '<br>PASS '+r.counts.pass+' · NEAR_PASS '+r.counts.near_pass+' · NG '+r.counts.ng+
        ' · 전체 UNKNOWN '+e.rows.filter(x=>x.evaluation.status==='UNKNOWN').length+'</div>'+
        '<div class="o-chart-wrap"><svg id="o-pareto-large" class="o-pareto-chart" role="img" aria-label="Pareto candidates for the selected performance objectives"></svg></div>'+
        '<div class="o-chart-caption" id="o-pareto-viewport"></div>'+
        '<div class="o-chart-caption">● 비교 사례 · ◯ Pareto · ★ 허용 후보 중 가중치 최선 · ◆ 현재 참조<br>'+
        (view.projection==='full'?'전체 3목적 판정입니다. 2D 투영에 연결선을 그리지 않습니다.':'점선은 관측 후보의 연결 가이드입니다. 중간 설계의 존재나 전역 최적성을 뜻하지 않습니다.')+
        '<br>Pareto는 성능 비교이며 예측 신뢰도가 아닙니다.'+
        (view.mode==='exploratory'?'<br>NG는 성능 미달 탐색용이며 합격 후보가 아닙니다.':'')+'</div>'+
        '<label class="o-field"><span>Candidate · 그래프의 점 또는 목록에서 선택</span><select id="o-pareto-case" '+(!r.rows.length?'disabled':'')+'>'+
        r.rows.map(row=>option(row.id,row.id+' · '+row.evaluation.status+(r.pareto_ids.includes(row.id)?' · Pareto':''),view.selected_id)).join('')+'</select></label>'+
        '<div id="o-pareto-detail"></div><details class="o-pareto-metadata"><summary>비교 조건과 제외 사유</summary><pre class="o-request" id="o-pareto-metadata"></pre></details>';
      hooks.show('Best candidates',html);
      $('o-pareto-cohort').onchange=function(){const g=groups[Number(this.value)];if(g){view.cohort_key=g.cohort_key;view.source_kind=g.source_kind;view.selected_id=null;open();mini()}};
      $('o-pareto-mode').onchange=function(){view.mode=this.value;view.selected_id=null;open();mini()};
      ['x','y'].forEach((key,i)=>$('o-pareto-'+key).onchange=function(){view.dimensions[i]=this.value;open();mini()});
      $('o-pareto-projection').onchange=function(){view.projection=this.value;open();mini()};
      $('o-pareto-line').onchange=function(){view.show_line=this.checked;draw()};
      $('o-pareto-refresh').onclick=()=>hooks.refreshCandidates();
      $('o-pareto-focus').onclick=function(){view.focus_front=!view.focus_front;open();mini()};
      $('o-pareto-apply-best').onclick=()=>best&&apply(best);
      $('o-pareto-undo-panel').onclick=undoApply;
      $('o-pareto-case').onchange=function(){select(this.value)};
      const selected=r.rows.find(x=>x.id===view.selected_id)||r.rows.find(x=>x.id===r.best_id)||r.rows[0];
      view.selected_id=selected?.id||null;if(selected)$('o-pareto-case').value=selected.id;
      detail(selected);
      const reasons={};e.rows.filter(x=>x.evaluation.status==='UNKNOWN').forEach(x=>x.evaluation.reasons.forEach(code=>{reasons[code]=(reasons[code]||0)+1}));
      const conditionRow=e.rows.find(x=>x.cohort_key===r.cohort_key&&x.source_kind===r.source_kind);
      $('o-pareto-metadata').textContent=JSON.stringify({conditions:conditionRow?.conditions||null,excluded_reasons:reasons,
        score_policy:e.score_policy,weights:e.category_weights,score_meaning:'낮을수록 좋음. 확률이 아니며 MTF 여유가 크면 음수가 될 수 있음.'},null,2);
      requestAnimationFrame(draw);
    }
    function detail(row){
      const el=$('o-pareto-detail');if(!el)return;
      if(!row){el.innerHTML='<p class="o-small">선택할 후보가 없습니다. 모델 예측 후보는 backend 연결 후 별도로 제공됩니다.</p>';return}
      const r=result(),reference=evaluated().rows.find(x=>x.id===hooks.getCurrentId()&&x.cohort_key===r.cohort_key&&x.source_kind===r.source_kind&&x.evaluation.comparison_ready);
      const metric=(label,a,b,unit='')=>'<tr><th>'+label+'</th><td>'+num(a)+unit+'</td><td>'+num(b)+unit+'</td></tr>';
      el.innerHTML='<div class="o-status-row"><strong>'+esc(row.id)+' · '+row.evaluation.status+'</strong><span>'+esc(sourceName(row.source_kind))+'</span></div>'+
        '<table class="o-target-table"><thead><tr><th>Metric</th><th>선택 후보</th><th>현재 참조 '+esc(reference?.id||'(다른 조건/미제공)')+'</th></tr></thead><tbody>'+
        metric('MTF 최악 목표 충족률',row.evaluation.mtf_quality*100,reference?.evaluation.mtf_quality*100,'%')+
        metric('RMS diameter @ 1.0F',row.metrics.spot_rms_diameter_um,reference?.metrics.spot_rms_diameter_um,' μm')+
        metric('Horizontal FOV · full',row.metrics.horizontal_fov_deg,reference?.metrics.horizontal_fov_deg,'°')+
        metric('가중치 점수 · 낮음 우수',row.evaluation.score,reference?.evaluation.score)+
        '</tbody></table><details><summary class="o-small">개별 목표 조건</summary><pre class="o-request" id="o-pareto-criteria"></pre></details>'+
        '<div class="o-demo-list"><button id="o-pareto-apply-selected" '+(busy||row.source_kind==='predicted'?'disabled':'')+'>'+
        (row.evaluation.status==='NG'?'미달 참조 설계로 적용':'선택 후보 적용')+'</button><button disabled>Apply predicted best · Not connected</button></div>';
      $('o-pareto-criteria').textContent=JSON.stringify(row.evaluation.criteria,null,2);
      $('o-pareto-apply-selected').onclick=()=>apply(row);
    }
    function select(id){view.selected_id=id;const row=result().rows.find(x=>x.id===id);if($('o-pareto-case'))$('o-pareto-case').value=id;detail(row);draw()}
    async function apply(row){
      if(busy)return;
      const owner=context(),pool=owner.candidateData,target=profile(),beforeEdit=editKey(),saved=hooks.snapshot();
      view.selected_id=row.id;
      const selected=JSON.stringify([view.cohort_key,view.source_kind,view.selected_id]);
      const sameData=()=>context()===owner&&owner.candidateData===pool&&profile()===target&&owner.candidateStatus==='ready';
      const current=()=>sameData()&&editKey()===beforeEdit&&JSON.stringify([view.cohort_key,view.source_kind,view.selected_id])===selected;
      busy=true;if(hooks.isActive())open();
      try{
        const data=await hooks.selectCase(row.id,current);
        if(data&&sameData()){
          undo={snapshot:saved,reference:lastReference,appliedKey:editKey()};mini();draw();
          hooks.notice(row.id+' 적용 완료'+(row.evaluation.status==='NG'?' · 목표 미달 참조 설계':'')+' · 되돌리기 가능');
        }else if(!current())hooks.notice('설계·후보 선택·DB 또는 목표가 변경되어 이전 후보를 적용하지 않았습니다.');
      }finally{busy=false;mini();if(hooks.isActive())open()}
    }
    function undoApply(){
      if(!canUndo()||busy)return;
      const saved=undo.snapshot;undo=null;hooks.restore(saved);refresh();hooks.notice('후보 적용 전 편집 상태를 복원했습니다.');
    }
    function drawOne(node,large){
      if(!global.d3||!node.clientWidth)return;
      const d3=global.d3,r=result(),w=node.clientWidth,h=large?Math.min(320,Math.max(200,global.innerHeight-520)):185;
      node.style.height=h+'px';node.style.minHeight=h+'px';
      const margin={left:large?65:50,right:18,top:18,bottom:48};
      const svg=d3.select(node).attr('viewBox','0 0 '+w+' '+h);svg.selectAll('*').remove();
      const rows=r.rows,pts=rows.map(row=>{const p=global.OpticsPareto.objectivePoint(row,view.dimensions);return {row,x:display(p.x,view.dimensions[0]),y:display(p.y,view.dimensions[1])}});
      function domain(values){if(!values.length)return [0,1];const ext=d3.extent(values),span=ext[1]-ext[0];return span?[ext[0]-span*.07,ext[1]+span*.07]:[ext[0]-Math.max(1,Math.abs(ext[0])*.05),ext[1]+Math.max(1,Math.abs(ext[1])*.05)]}
      const front=new Set(r.pareto_ids),focus=view.focus_front?pts.filter(p=>front.has(p.row.id)):pts;
      const extentPoints=focus.length?focus:pts;
      const x=d3.scaleLinear().domain(domain(extentPoints.map(p=>p.x))).nice().range([margin.left,w-margin.right]);
      const y=d3.scaleLinear().domain(domain(extentPoints.map(p=>p.y))).nice().range([h-margin.bottom,margin.top]);
      const visible=pts.filter(p=>p.x>=x.domain()[0]&&p.x<=x.domain()[1]&&p.y>=y.domain()[0]&&p.y<=y.domain()[1]);
      if(large&&$('o-pareto-viewport'))$('o-pareto-viewport').textContent=(view.focus_front?'Pareto 주변 확대':'전체 분포')+' · 화면 범위 '+visible.length+' / 비교 집합 '+pts.length+' · 확대는 Pareto 판정을 바꾸지 않습니다.';
      const clip='pareto-clip-'+node.id;
      svg.append('defs').append('clipPath').attr('id',clip).append('rect').attr('x',margin.left).attr('y',margin.top).attr('width',Math.max(1,w-margin.left-margin.right)).attr('height',h-margin.top-margin.bottom);
      const marks=svg.append('g').attr('clip-path','url(#'+clip+')');
      svg.append('g').attr('transform','translate(0,'+(h-margin.bottom)+')').call(d3.axisBottom(x).ticks(large?5:3).tickFormat(d3.format('.3~s')));
      svg.append('g').attr('transform','translate('+margin.left+',0)').call(d3.axisLeft(y).ticks(4).tickFormat(d3.format('.3~s')));
      svg.append('text').attr('x',(margin.left+w-margin.right)/2).attr('y',h-8).attr('text-anchor','middle').text(axisName(view.dimensions[0]));
      svg.append('text').attr('transform','rotate(-90)').attr('x',-(margin.top+h-margin.bottom)/2).attr('y',large?17:12).attr('text-anchor','middle').text(axisName(view.dimensions[1]));
      if(!pts.length){svg.append('text').attr('x',w/2).attr('y',h/2).attr('text-anchor','middle').text('Pareto 후보 없음');return}
      if(view.show_line&&view.projection==='pair'&&r.line_points.length>1){
        marks.append('path').attr('data-pareto-guide','true').attr('fill','none').attr('stroke','var(--o-blue)').attr('stroke-width',1.5).attr('stroke-dasharray','5 4')
          .attr('d',d3.line().x(p=>x(display(p.x,view.dimensions[0]))).y(p=>y(display(p.y,view.dimensions[1])))(r.line_points));
      }
      marks.append('g').selectAll('circle').data(pts).join('circle').attr('data-case-id',p=>p.row.id).attr('data-pareto',p=>String(front.has(p.row.id)))
        .attr('cx',p=>x(p.x)).attr('cy',p=>y(p.y)).attr('r',p=>front.has(p.row.id)?5:3)
        .attr('fill',p=>p.row.evaluation.status==='NG'?'var(--o-gray)':'var(--o-teal)')
        .attr('stroke',p=>front.has(p.row.id)?'var(--o-blue)':'none').attr('stroke-width',2).attr('opacity',.8);
      const best=pts.find(p=>p.row.id===r.best_id),reference=pts.find(p=>p.row.id===hooks.getCurrentId());
      if(best)marks.append('path').attr('data-weighted-best',best.row.id).attr('d',d3.symbol().type(d3.symbolStar).size(110)()).attr('transform','translate('+x(best.x)+','+y(best.y)+')').attr('fill','var(--o-warn)');
      if(reference)marks.append('path').attr('data-reference-case',reference.row.id).attr('d',d3.symbol().type(d3.symbolDiamond).size(70)()).attr('transform','translate('+x(reference.x)+','+y(reference.y)+')').attr('fill','none').attr('stroke','var(--o-purple)').attr('stroke-width',2);
      const selected=pts.find(p=>p.row.id===view.selected_id);
      if(selected)marks.append('circle').attr('cx',x(selected.x)).attr('cy',y(selected.y)).attr('r',9).attr('fill','none').attr('stroke','var(--o-ink)').attr('stroke-width',1);
      let tip=node.parentElement.querySelector('.o-chart-tip');if(!tip){tip=document.createElement('div');tip.className='o-chart-tip';node.parentElement.appendChild(tip)}
      const nearest=e=>{const p=d3.pointer(e,node),item=d3.least(visible,q=>(x(q.x)-p[0])**2+(y(q.y)-p[1])**2);
        return {p,item:item&&(x(item.x)-p[0])**2+(y(item.y)-p[1])**2<=400?item:null}};
      svg.append('rect').attr('x',margin.left).attr('y',margin.top).attr('width',Math.max(1,w-margin.left-margin.right)).attr('height',h-margin.top-margin.bottom).attr('fill','transparent')
        .on('pointermove',function(e){const {p,item}=nearest(e);if(!item){tip.style.display='none';return}tip.textContent=item.row.id+' · '+item.row.evaluation.status+'\n'+axisName(view.dimensions[0])+': '+num(item.x)+'\n'+axisName(view.dimensions[1])+': '+num(item.y);tip.style.display='block';tip.style.left=Math.max(0,Math.min(p[0]+8,w-tip.offsetWidth-4))+'px';tip.style.top=Math.max(0,p[1]-tip.offsetHeight-5)+'px'})
        .on('pointerleave',()=>{tip.style.display='none'})
        .on('click',function(e){const {item}=nearest(e);if(!item)return;view.selected_id=item.row.id;if(!hooks.isActive())open();else select(item.row.id)});
    }
    function draw(){mini();const small=$('o-pareto-mini'),large=$('o-pareto-large');if(small)drawOne(small,false);if(large)drawOne(large,true)}
    function restore(saved){view={...defaults(),...(saved||{}),dimensions:[...(saved?.dimensions||defaults().dimensions)]};selections={};undo=null}
    $('o-pareto-open').onclick=open;$('o-pareto-undo').onclick=undoApply;
    return {open,refresh,draw,snapshot:()=>copy(view),restore};
  };
})(typeof window!=='undefined'?window:globalThis);
