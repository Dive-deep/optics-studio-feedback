/* Shared stored-result plotting for the workspace and independent chart windows. */
(function (root) {
  "use strict";
  let sequence=0;
  const copy=value=>JSON.parse(JSON.stringify(value));
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  function fail(){throw new Error('그래프 데이터 형식이 올바르지 않습니다.');}
  function viewState(value){
    if(value===null||value===undefined)return {k:1,x:0,y:0};
    if(!value||![value.k,value.x,value.y].every(finite)||value.k<1||value.k>12)fail();
    return {k:value.k,x:value.x,y:value.y};
  }
  function normalizePayload(value){
    if(!value||value.schema_version!==1||!['mtf','spot'].includes(value.kind))fail();
    for(const key of ['revision','reference_id','source_label','conditions_label'])if(typeof value[key]!=='string')fail();
    if(!value.condition_metadata||typeof value.condition_metadata!=='object'||Array.isArray(value.condition_metadata))fail();
    const units=value.units;if(!units||units.x!==(value.kind==='mtf'?'lp/mm':'µm')||units.y!==(value.kind==='mtf'?'fraction':'µm'))fail();
    if(value.rms_diameter_um!==null&&(!finite(value.rms_diameter_um)||value.rms_diameter_um<0))fail();
    viewState(value.view);
    const rows=value[value.kind];if(!Array.isArray(rows))fail();
    const seen=new Set();
    rows.forEach(row=>{
      if(!row||typeof row!=='object')fail();
      if(value.kind==='mtf'){
        if(![row.field_norm,row.frequency_lp_per_mm,row.mtf].every(finite)||row.frequency_lp_per_mm<0||
          !['SAGITTAL','TANGENTIAL'].includes(row.orientation))fail();
        const key=JSON.stringify([row.field_norm,row.orientation,row.frequency_lp_per_mm]);
        if(seen.has(key))fail();seen.add(key);
      }else if(!finite(row.x)||!finite(row.y)||
        (row.wavelength_nm!==undefined&&row.wavelength_nm!==null&&!finite(row.wavelength_nm)))fail();
    });
    return copy(value);
  }
  function mtfSeries(payload){
    const groups=new Map();
    (payload.mtf||[]).forEach(row=>{
      const key=JSON.stringify([row.field_norm,row.orientation]);
      if(!groups.has(key))groups.set(key,{key,field_norm:row.field_norm,orientation:row.orientation,values:[]});
      groups.get(key).values.push({...row});
    });
    return [...groups.values()].sort((a,b)=>a.field_norm-b.field_norm||a.orientation.localeCompare(b.orientation))
      .map(series=>({...series,values:series.values.sort((a,b)=>a.frequency_lp_per_mm-b.frequency_lp_per_mm)}));
  }
  function mtfAt(series,frequency){
    const rows=series.values;
    if(!rows.length||!finite(frequency)||frequency<rows[0].frequency_lp_per_mm||frequency>rows.at(-1).frequency_lp_per_mm)return null;
    const exact=rows.find(row=>row.frequency_lp_per_mm===frequency);if(exact)return exact.mtf;
    const index=rows.findIndex(row=>row.frequency_lp_per_mm>frequency);
    if(index<1)return null;
    const a=rows[index-1],b=rows[index],ratio=(frequency-a.frequency_lp_per_mm)/(b.frequency_lp_per_mm-a.frequency_lp_per_mm);
    return a.mtf+ratio*(b.mtf-a.mtf);
  }
  function render(node,raw,options={}){
    const payload=normalizePayload(raw),d3=root.d3;
    if(!d3)throw new Error('그래프 렌더러를 불러오지 못했습니다.');
    const bounds=node.getBoundingClientRect(),width=bounds.width,height=bounds.height;
    if(!width||!height)return null;
    const kind=payload.kind,interactive=!!options.interactive,svg=d3.select(node);
    const margin={left:48,right:14,top:12,bottom:43};
    if(kind==='spot'){
      const side=Math.max(1,Math.min(width-62,height-55));
      margin.left=(width-side)/2;margin.right=(width-side)/2;margin.bottom=height-margin.top-side;
    }
    svg.on('.zoom',null).selectAll('*').remove();svg.attr('viewBox','0 0 '+width+' '+height);
    let currentView=viewState(options.view===undefined?payload.view:options.view),restoring=true;
    const rows=payload[kind],series=kind==='mtf'?mtfSeries(payload):[];
    let tip=node.parentElement.querySelector('[data-chart-tooltip]');
    if(!tip){tip=node.ownerDocument.createElement('div');tip.className='o-chart-tip';tip.dataset.chartTooltip='true';node.parentElement.appendChild(tip)}
    tip.style.display='none';
    if(!rows.length){
      svg.append('text').attr('x',width/2).attr('y',height/2).attr('text-anchor','middle').text('데이터 미제공');
      return {getView:()=>copy(currentView),zoomIn(){},zoomOut(){},reset(){},destroy(){svg.on('.zoom',null);tip.style.display='none'}};
    }
    const x0=d3.scaleLinear().range([margin.left,width-margin.right]),y0=d3.scaleLinear().range([height-margin.bottom,margin.top]);
    if(kind==='mtf'){x0.domain([0,Math.max(1,d3.max(rows,row=>row.frequency_lp_per_mm))]);y0.domain([0,100])}
    else{const extent=d3.max(rows,row=>Math.max(Math.abs(row.x),Math.abs(row.y)))*1.15||1;x0.domain([-extent,extent]);y0.domain([-extent,extent])}
    let x=x0,y=y0;
    const clip='optics-chart-clip-'+(++sequence),plotWidth=Math.max(1,width-margin.left-margin.right),plotHeight=Math.max(1,height-margin.top-margin.bottom);
    svg.append('defs').append('clipPath').attr('id',clip).append('rect').attr('x',margin.left).attr('y',margin.top).attr('width',plotWidth).attr('height',plotHeight);
    const gx=svg.append('g').attr('transform','translate(0,'+(height-margin.bottom)+')'),gy=svg.append('g').attr('transform','translate('+margin.left+',0)');
    svg.append('text').attr('x',(margin.left+width-margin.right)/2).attr('y',height-7).attr('text-anchor','middle').text(kind==='mtf'?'Spatial frequency · lp/mm':'x · µm');
    svg.append('text').attr('transform','rotate(-90)').attr('x',-(margin.top+height-margin.bottom)/2).attr('y',12).attr('text-anchor','middle').text(kind==='mtf'?'MTF · %':'y · µm');
    const marks=svg.append('g').attr('clip-path','url(#'+clip+')');
    const guide=svg.append('line').attr('stroke','var(--o-muted)').attr('stroke-dasharray','3 3').attr('y1',margin.top).attr('y2',height-margin.bottom).style('display','none');
    const color=series=>series.field_norm===0?'var(--o-blue)':'var(--o-purple)';
    function paint(){
      gx.call(d3.axisBottom(x).ticks(width<350?3:5));gy.call(d3.axisLeft(y).ticks(4));marks.selectAll('*').remove();
      if(kind==='mtf')series.forEach(group=>{
        marks.append('path').datum(group.values).attr('fill','none').attr('stroke',color(group)).attr('stroke-width',1.7)
          .attr('stroke-dasharray',group.orientation==='TANGENTIAL'?'5 3':null)
          .attr('d',d3.line().x(row=>x(row.frequency_lp_per_mm)).y(row=>y(row.mtf*100)));
        if(group.values.length===1)marks.append('circle').attr('cx',x(group.values[0].frequency_lp_per_mm)).attr('cy',y(group.values[0].mtf*100)).attr('r',2.6).attr('fill',color(group));
      });
      else marks.selectAll('circle').data(rows).join('circle').attr('cx',row=>x(row.x)).attr('cy',row=>y(row.y)).attr('r',2.6).attr('fill','var(--o-blue)').attr('opacity',.6);
    }
    paint();
    const hit=svg.append('rect').attr('data-chart-hit','true').attr('x',margin.left).attr('y',margin.top).attr('width',plotWidth).attr('height',plotHeight).attr('fill','transparent');
    hit.on('pointermove click',function(event){
      const point=d3.pointer(event,node);let label='';
      if(kind==='mtf'){
        const frequency=x.invert(point[0]);
        if(frequency<x0.domain()[0]||frequency>x0.domain()[1]){guide.style('display','none');tip.style.display='none';return}
        guide.style('display',null).attr('x1',point[0]).attr('x2',point[0]);label=frequency.toFixed(2)+' lp/mm';
        series.forEach(group=>{const value=mtfAt(group,frequency);label+='\n'+group.field_norm+'F '+(group.orientation==='SAGITTAL'?'S':'T')+': '+(value===null?'—':(value*100).toFixed(1)+'%')});
      }else{
        const row=d3.least(rows,item=>(x(item.x)-point[0])**2+(y(item.y)-point[1])**2);
        label='x / y: '+row.x.toFixed(2)+' / '+row.y.toFixed(2)+' µm';
        if(finite(row.wavelength_nm))label+='\n'+row.wavelength_nm+' nm';
      }
      tip.textContent=label;tip.style.display='block';tip.style.left=Math.max(4,Math.min(point[0]+12,width-tip.offsetWidth-5))+'px';tip.style.top=Math.max(0,point[1]-tip.offsetHeight-8)+'px';
    }).on('pointerleave',function(){tip.style.display='none';guide.style('display','none')});
    let zoom=null;
    if(interactive){
      zoom=d3.zoom().scaleExtent([1,12]).extent([[margin.left,margin.top],[width-margin.right,height-margin.bottom]])
        .on('zoom',function(event){
          x=event.transform.rescaleX(x0);y=kind==='mtf'?y0:event.transform.rescaleY(y0);
          currentView={k:event.transform.k,x:event.transform.x,y:event.transform.y};paint();tip.style.display='none';
          if(!restoring)options.onViewChange?.(copy(currentView));
        });
      svg.call(zoom);svg.call(zoom.transform,d3.zoomIdentity.translate(currentView.x,currentView.y).scale(currentView.k));
    }
    restoring=false;
    return {getView:()=>copy(currentView),zoomIn(){if(zoom)svg.call(zoom.scaleBy,1.4)},zoomOut(){if(zoom)svg.call(zoom.scaleBy,1/1.4)},
      reset(){if(zoom)svg.call(zoom.transform,d3.zoomIdentity)},destroy(){svg.on('.zoom',null);tip.style.display='none'}};
  }
  root.OpticsChart={normalizePayload,mtfSeries,mtfAt,render};
})(typeof window!=='undefined'?window:globalThis);
