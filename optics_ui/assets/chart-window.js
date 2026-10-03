/* An isolated chart page: only the native chart channel is available here. */
(function (root) {
  "use strict";
  const document=root.document,$=id=>document.getElementById(id),copy=value=>JSON.parse(JSON.stringify(value));
  let payload=null,view={k:1,x:0,y:0},controller=null,bridge=null,error=null,pending=false;
  function render(){
    if(!payload)return;
    controller?.destroy();
    controller=root.OpticsChart.render($('chart-plot'),payload,{interactive:true,view,
      onViewChange:function(next){
        view=copy(next);
        if(bridge?.viewChanged)bridge.viewChanged(JSON.stringify({kind:payload.kind,revision:payload.revision,view}));
      }});
  }
  function setData(value){
    try{
      const clean=root.OpticsChart.normalizePayload(typeof value==='string'?JSON.parse(value):value);
      payload=clean;view=copy(payload.view||{k:1,x:0,y:0});error=null;
      $('chart-title').textContent=payload.kind==='mtf'?'MTF · Full curve':'Spot · 1.0F';
      $('chart-source').textContent=payload.source_label+' · Reference '+payload.reference_id;
      $('chart-conditions').textContent=payload.conditions_label;
      $('chart-condition-details').textContent=JSON.stringify(payload.condition_metadata,null,2);
      $('chart-legend').textContent=payload.kind==='mtf'
        ? root.OpticsChart.mtfSeries(payload).map(group=>group.field_norm+'F '+(group.orientation==='SAGITTAL'?'S —':'T – –')).join('    ')
        : 'RMS diameter '+(payload.rms_diameter_um===null?'—':payload.rms_diameter_um.toFixed(2)+' µm');
      $('chart-error').hidden=true;render();return true;
    }catch(_){error='그래프 데이터를 표시할 수 없습니다. 이전 결과가 있으면 그대로 유지합니다.';$('chart-error').textContent=error;$('chart-error').hidden=false;return false}
  }
  function schedule(){if(pending)return;pending=true;requestAnimationFrame(function(){pending=false;render()})}
  root.opticsChartWindow={setData,
    getState:function(){return {kind:payload?.kind||null,revision:payload?.revision||null,reference_id:payload?.reference_id||null,
      view:copy(controller?.getView()||view),point_count:payload?payload[payload.kind].length:0,error,rendered:!!controller}},
    zoomIn:function(){controller?.zoomIn()},zoomOut:function(){controller?.zoomOut()},reset:function(){controller?.reset()}};
  $('chart-zoom-in').onclick=root.opticsChartWindow.zoomIn;$('chart-zoom-out').onclick=root.opticsChartWindow.zoomOut;$('chart-reset').onclick=root.opticsChartWindow.reset;
  new ResizeObserver(schedule).observe($('chart-wrap'));
  if(root.qt?.webChannelTransport&&typeof QWebChannel==='function'){
    new QWebChannel(root.qt.webChannelTransport,function(channel){
      bridge=channel.objects.chart;
      if(!bridge){error='그래프 연결을 사용할 수 없습니다.';$('chart-error').textContent=error;$('chart-error').hidden=false;return}
      bridge.dataChanged.connect(setData);bridge.chartData(setData);
    });
  }
})(window);
