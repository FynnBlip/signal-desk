// Actual lab.js with memory-only DOM and transport, no paid requests.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
function harness(){
 const elements=new Map();
 const el=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',hidden:false,dataset:{},disabled:false,setAttribute(){},classList:{toggle(){}}});return elements.get(id)};
 const c=vm.createContext({console,document:{getElementById:el,querySelector:()=>el('switch'),querySelectorAll:()=>[],addEventListener(){}},location:{hash:''},history:{pushState(){}},window:{scrollTo(){}},setInterval(){},fetch(){throw Error('Real network forbidden')}});
 vm.runInContext(fs.readFileSync('app/lab.js','utf8'),c);return {el,run:s=>vm.runInContext(s,c)};
}
(async()=>{
 for(const p of ['evaluate','loop','detail-OOFFICE']){
  const {el,run}=harness();
  run(`labData={status:{experiment_id:'e',baseline:'v1',candidate:'v2',rounds:[]},job:{state:'running',done:0}};labPage=${JSON.stringify(p)};labPair=()=>{}`);
  await run('labPanel()');const before=el('labPanel').innerHTML;
  run(`globalThis.fresh={status:labData.status,job:{state:'done',result:{status:'ok',experiment_id:'e',run_id:'finished-run',baseline:'v1',candidate:'v2',judge:{baseline_regular_pq:6,candidate_regular_pq:7,regular_delta:1},rows:[{scene_id:'OOFFICE',stem:'sample',baseline_pq:6,candidate_pq:7}],blind_pairs:[],decision:{action:'accept'}}}};fetch=async url=>({ok:true,json:async()=>url.endsWith('/status')?fresh.status:fresh.job})`);
  await run('labRefresh()');assert.notEqual(el('labPanel').innerHTML,before,`${p} must update without re-entry`);
  assert.match(el('labExecution').textContent,/结果就绪/);
  const request=run('labPanelRequest');await run('labRefresh()');
  assert.equal(run('labPanelRequest'),request,'unchanged result must not rebuild audio');
  run(`fresh.job={state:'idle',result:null}`);await run('labRefresh()');
  if(p==='loop')assert.match(el('labPanel').innerHTML,/当前没有待复核结果/);
 }
 {
  const {el,run}=harness();
  run(`labData={status:{experiment_id:'e',baseline:'v1',config:{},benchmark:{ready:true}},job:{state:'idle'}};labPage='run';globalThis.postResolve=null;globalThis.runCalls=0;labPost=(url)=>url.endsWith('/run')?(runCalls++,new Promise(r=>postResolve=r)):Promise.resolve({status:'ok'});fetch=async url=>({ok:true,json:async()=>url.endsWith('/status')?labData.status:labData.job})`);
  el('labBaseline').value='v1';el('labCandidate').value='v2';
  const submitting=run('labSubmitRun({preventDefault(){}})');await Promise.resolve();await Promise.resolve();
  run('labData.status.candidate="v2"');await run('labRefresh()');
  assert.equal(el('labStart').disabled,true,'slow run response remains locked');
  await run('labSubmitRun({preventDefault(){}})');assert.equal(run('runCalls'),1);
  run('postResolve({status:"ok",run_id:"r"})');await submitting;
 }
 {
  const {run}=harness();
  run(`labData={status:{experiment_id:'e'},job:{state:'running',run_id:'acknowledged'}};globalThis.oldResolve=null;globalThis.reads=0;fetch=async url=>({ok:true,json:async()=>{reads++;if(reads===1)return new Promise(r=>oldResolve=r);return url.endsWith('/status')?{experiment_id:'e'}:{state:'running',run_id:'acknowledged'}}})`);
  const polling=run('labRefresh()');await Promise.resolve();await Promise.resolve();await Promise.resolve();
  run('labPollEpoch++;oldResolve({experiment_id:"old-experiment"})');await polling;
  assert.equal(run('labData.status.experiment_id'),'e','pre-mutation poll cannot overwrite the acknowledged state');
  assert.equal(run('labData.job.run_id'),'acknowledged');
 }
 {
  const {el,run}=harness();
  run(`labData={status:{experiment_id:'e',baseline:'v1',candidate:'v2',config:{},benchmark:{ready:true}},job:{state:'idle'}};labPage='run';globalThis.calls=[];globalThis.configResolve=null;labPost=(url,payload)=>{calls.push({url,payload});if(url.endsWith('/config'))return new Promise(r=>configResolve=r);return Promise.resolve({status:'ok',run_id:'r'})};fetch=async url=>({ok:true,json:async()=>url.endsWith('/status')?labData.status:labData.job})`);
  el('labBaseline').value='v1';el('labCandidate').value='v2';
  const first=run('labSubmitRun({preventDefault(){}})');
  await run('labRefresh()');assert.equal(el('labStart').disabled,true);assert.equal(el('labCandidate').disabled,true);
  await run('labSubmitRun({preventDefault(){}})');assert.equal(run('calls.length'),1);
  run('configResolve({status:"ok"})');await first;
  assert.equal(run('calls.filter(x=>x.url.endsWith("/run")).length'),1);
  assert.equal(el('labStart').disabled,true,'successful launch stays locked');
  run(`labData.job={state:'error'};labRunStatus()`);assert.equal(el('labStart').disabled,false);
  run(`labPost=async()=>{throw Error('fixture config failure')}`);await run('labSubmitRun({preventDefault(){}})');
  assert.equal(run('labSubmitting'),false);assert.equal(el('labStart').disabled,false);
 }
 {
  const {el,run}=harness();
  run(`labVoiceData={cohort_id:'c',embedding:{source_dimensions:21,explained_variance:[.4,.2,.1]},points:[{file:'a.wav',name:'a',cluster:1,x:1,y:2,z:3,f0_mean:100,f1_mean:200,f2_mean:1200,audio_available:true}]};labVoiceSelection='a.wav';labVoiceFilter=1;labRenderVoice()`);
  assert.match(el('voiceSelection').innerHTML,/a.wav/);
  run(`labVoiceData.points=[];labRenderVoice()`);
  run(`labVoiceData.points=[{file:'b.wav',name:'b',cluster:0,x:1,y:2,z:3,f0_mean:100,f1_mean:200,f2_mean:1200}];labRenderVoice()`);
  assert.equal(run('labVoiceSelection'),null);
 }
 {
  const {el,run}=harness();
  run(`labData={status:{},job:{}};labPage='voice';globalThis.cohort='c';labGet=async()=>({cohort_id:cohort,embedding:{source_dimensions:21},points:[{file:'a.wav',name:'a',cluster:1,x:1,y:2,z:3,f0_mean:100,f1_mean:200,f2_mean:1200,audio_available:true}]})`);
  await run('labPanel()');run('labVoiceFilter=1;labSelectVoice(0)');
  await run('labPanel()');assert.equal(run('labVoiceFilter'),1);assert.match(el('voiceSelection').innerHTML,/a.wav/);
  run('cohort="other"');await run('labPanel()');assert.equal(run('labVoiceSelection'),null);assert.equal(run('labVoiceFilter'),null);
 }
 {
  const {run}=harness();
  run(`labData={job:{result:{run_id:'review',baseline:'v1',candidate:'v2',decision:{action:'accept'}}}};labReviewRun='review';globalThis.action=null;globalThis.posts=[];globalThis.refreshedEpoch=null;labDialog=(title,body,callback)=>action=callback;labGet=async()=>({result:{run_id:'review'}});labPost=async(url,payload)=>posts.push({url,payload});labRefresh=async()=>refreshedEpoch=labPollEpoch;labOpen=()=>{};labApplyDialog()`);
  await run('action()');
  assert.equal(run('refreshedEpoch'),1,'accepted result invalidates pre-confirmation polls before refresh');
  assert.equal(run('posts.length'),1);
  run(`labGet=async()=>({result:{run_id:'different'}});labApplyDialog()`);
  await assert.rejects(run('action()'),/结果已变化/);
  assert.equal(run('posts.length'),1,'changed result cannot be applied');
 }
 console.log('PASS: terminal results refresh in place, unchanged polling preserves panel, pending submit lock, one request chain, retry, voice restoration, confirmation poll invalidation');
})().catch(e=>{console.error(e);process.exitCode=1});
