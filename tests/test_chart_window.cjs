const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function payload(view=null){return {schema_version:1,kind:'spot',revision:'chart-1',reference_id:'D1',source_label:'합성 DB',conditions_label:'20°C',condition_metadata:{temperature_c:20},units:{x:'µm',y:'µm'},spot:[{x:1,y:2}],rms_diameter_um:1.6,view};}
function setup(){
 const nodes=new Map(),element=()=>({textContent:'',hidden:false,disabled:false,style:{},addEventListener(){}});
 const document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)}};
 const sent=[];let listener,resize;
 const bridge={chartData:callback=>callback(JSON.stringify(payload())),dataChanged:{connect:fn=>{listener=fn}},viewChanged:raw=>sent.push(JSON.parse(raw))};
 const window={document,qt:{webChannelTransport:{}}};
 const sandbox={window,document,qt:window.qt,requestAnimationFrame:fn=>{fn();return 1},ResizeObserver:class{constructor(fn){resize=fn}observe(){}},QWebChannel:function(_,callback){callback({objects:{chart:bridge}})}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('design/optics-chart.js','utf8'),sandbox);
 window.OpticsChart.render=(_,data,options)=>{
  let view={...(options.view||{k:1,x:0,y:0})};return {getView:()=>view,destroy(){},
   zoomIn(){view={...view,k:2};options.onViewChange(view)},zoomOut(){view={...view,k:1};options.onViewChange(view)},
   reset(){view={k:1,x:0,y:0};options.onViewChange(view)}};};
 vm.runInContext(fs.readFileSync('design/chart-window.js','utf8'),sandbox);
 return {api:window.opticsChartWindow,nodes,sent,receive:raw=>listener(raw),resize:()=>resize()};
}
test('private chart bridge renders data and sends actual local view changes',()=>{
 const x=setup();assert.equal(x.api.getState().revision,'chart-1');assert.equal(x.sent.length,0);
 x.api.zoomIn();assert.equal(x.api.getState().view.k,2);assert.equal(x.sent.at(-1).revision,'chart-1');
 assert.equal(x.sent.at(-1).kind,'spot');
});
test('resize preserves local view without generating a new edit',()=>{
 const x=setup();x.api.zoomIn();const count=x.sent.length;x.resize();
 assert.equal(x.api.getState().view.k,2);assert.equal(x.sent.length,count);
});
test('explicit data refresh applies saved view even for the same reference revision',()=>{
 const x=setup();x.api.zoomIn();const count=x.sent.length;
 x.receive(JSON.stringify(payload({k:3,x:12,y:-8})));
 assert.equal(x.api.getState().view.k,3);assert.equal(x.api.getState().view.x,12);assert.equal(x.sent.length,count);
});
test('malformed refresh preserves the last chart with an error status',()=>{
 const x=setup();x.receive('{broken');
 assert.equal(x.api.getState().reference_id,'D1');assert.ok(x.api.getState().error);
});
