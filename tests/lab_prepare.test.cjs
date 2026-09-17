// Current source, memory-only transport. No external generation or inference.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
function harness(){
 const nodes=new Map(),el=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',disabled:false,value:'',hidden:false,setAttribute(){},classList:{toggle(){}}});return nodes.get(id)};
 const c=vm.createContext({console,document:{getElementById:el,querySelector:()=>el('switch'),querySelectorAll:()=>[],addEventListener(){}},location:{hash:''},history:{pushState(){}},window:{scrollTo(){}},setInterval(){},fetch(){throw Error('Real network forbidden')}});
 vm.runInContext(fs.readFileSync('app/lab.js','utf8'),c);
 const run=s=>vm.runInContext(s,c);
 run(`labPage='tts';labPrepareLabel='reference';labTTSProvider={ready:true,name:'Mock'};globalThis.posts=[];globalThis.dialog=null;labDialog=(title,body,action)=>dialog={title,body,action};labPost=async(url,payload)=>{posts.push({url,payload});return {status:'ok',selected_count:26,api_calls:26,probe_text:'probe',version_label:payload.version_label,voices:[],cohort_id:'c'}};labGet=async url=>url.endsWith('/job')?{state:'done',done:26,total:26}:{cohorts:[]}`);
 return {el,run};
}
(async()=>{
 {
  const {run}=harness();run(`labPrepareLabel=''`);await run('labPreviewPrepare({preventDefault(){}})');assert.equal(run('posts.length'),0);
  run(`labPrepareLabel='reference';labTTSProvider.ready=false`);await run('labPreviewPrepare(null)');assert.equal(run('posts.length'),0);
 }
 {
  const {run}=harness();run(`labRememberPrepareLabel('return label')`);
  assert.equal(run('labPrepareLabel'),'return label','unsubmitted input must survive leaving the page');
 }
 {
  const {el,run}=harness();run(`labPrepareJob={state:'running',done:3,total:26};labPrepareMessage='accepted';labGet=async()=>{throw Error('offline')}`);
  await run('labPreparePoll()');assert.match(el('labPrepareFeedback').textContent,/暂未更新/);
  run(`labGet=async()=>({state:'running',done:3,total:26})`);await run('labPreparePoll()');
  assert.equal(el('labPrepareFeedback').textContent,'accepted','recovered status cannot keep showing a connection error');
 }
 {
  const {el,run}=harness();el('labPrepareLabel').value='typed label';
  await run('labPreviewPrepare({preventDefault(){}})');
  assert.equal(run('posts[0].payload.version_label'),'typed label','submit reads the actual textbox, not an inline name-shadowed variable');
 }
 {
  const {run}=harness();await run('labPreviewPrepare(null)');assert.equal(run('posts.length'),1);assert.match(run('dialog.body'),/最多 26 次/);
  assert.equal(run('posts[0].payload.benchmark'),true);assert.equal(run('posts[0].payload.count'),26);assert.equal(run('posts[0].payload.seed'),42);
  assert.equal(run('posts.some(p=>p.url.endsWith("/run"))'),false,'preview and cancellation cannot generate');
  run(`labPost=async()=>({status:'ok',selected_count:10})`);await run('labPreviewPrepare(null)');assert.match(run('labPrepareMessage'),/目录不足/);
 }
 {
  const {el,run}=harness();run(`globalThis.resolveRun=null;labPost=(url,payload)=>{posts.push({url,payload});return new Promise(r=>resolveRun=r)}`);
  const first=run(`labStartPrepare({count:26})`);assert.equal(el('labPreparePreview').disabled,true);
  await assert.rejects(run(`labStartPrepare({count:26})`),/正在进行/);assert.equal(run('posts.length'),1);
  run(`resolveRun({status:'ok',cohort_id:'c'})`);await first;assert.equal(run('labPrepareJob.state'),'done');assert.equal(run('labPrepareBusy'),false);
 }
 {
  const {run}=harness();run(`labPost=async()=>{throw Error('lost response')};labGet=async()=>{throw Error('offline')}`);
  await assert.rejects(run(`labStartPrepare({count:26})`),/lost response/);assert.equal(run('labPrepareUncertain'),true);
  await assert.rejects(run(`labStartPrepare({count:26})`),/待核对/);
  run(`labGet=async()=>({state:'running',done:3,total:26})`);await run('labPreparePoll()');assert.equal(run('labPrepareUncertain'),false);assert.equal(run('labPrepareJob.done'),3);
 }
 {
  const {run}=harness();run(`labCohorts=[{id:'partial',version_label:'old',seed:7,language_scope:'mandarin',probe_text:'old probe',requested_count:26,status:'partial'}]`);
  await run('labPreviewPrepare(null,0)');assert.equal(run('posts[0].payload.cohort_id'),'partial');assert.equal(run('posts[0].payload.probe_text'),'old probe');assert.equal(run('posts[0].payload.seed'),7);
  run(`labPost=async()=>({status:'reused',cohort_id:'partial',message:'cache'});labGet=async url=>url.endsWith('/job')?{state:'idle'}:{cohorts:[]}`);
  await run('dialog.action()');assert.equal(run('labChosenCohort'),'partial');
 }
 {
  const {run}=harness();run(`labChosenCohort='c';labCohorts=[{id:'c',name:'cache',status:'ready',requested_count:26,completed_count:26,can_activate:false,n_clusters:0}];labRefresh=async()=>{};labPanel=async()=>{};labPage='voice'`);
  run('labActivateCohort()');assert.equal(run('dialog'),null,'unqualified cache cannot activate');
  run('labAnalyzeCohort()');await run('dialog.action()');assert.equal(run('posts[0].payload.k'),4);assert.equal(run('posts[0].payload.use_anchor'),true);
  run(`labCohorts[0].can_activate=true;labCohorts[0].n_clusters=4;labPost=async()=>{throw Error('activation failed')};labActivateCohort()`);
  await assert.rejects(run('dialog.action()'),/activation failed/);assert.match(run('labPrepareMessage'),/操作失败/);assert.equal(run('labCohorts[0].active'),undefined);assert.equal(run('labPrepareBusy'),false);
 }
 console.log('PASS: resource preview guards, no implicit paid run, delayed submit lock, uncertain request recovery, exact partial payload, cluster/activation validation');
})().catch(e=>{console.error(e);process.exitCode=1});
