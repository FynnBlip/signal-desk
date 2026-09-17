const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',hidden:true,dataset:{},setAttribute(){},classList:{add(){},toggle(){}},disabled:false});return elements.get(id);};
const context=vm.createContext({console,document:{getElementById:element,querySelector:()=>element('switch'),querySelectorAll:()=>[],addEventListener(){}},location:{hash:''},history:{pushState(){}},window:{scrollTo(){}},setInterval(){},fetch:async()=>{throw Error('Unexpected network');}});
vm.runInContext(readFileSync('app/lab.js','utf8'),context);
const run=code=>vm.runInContext(code,context);
(async()=>{
 run(`labReviewRun='r1';labPost=()=>new Promise(resolve=>{globalThis.resolveVote=resolve})`);
 element('labPairSelect').value='sample-a';
 const saving=run(`labVote('A')`);
 assert.equal(element('labVoteFeedback').textContent,'正在记录听感…');
 element('labPairSelect').value='sample-b';element('labVoteFeedback').textContent='A/B 已盲化，不显示版本身份。';
 run(`resolveVote({status:'ok'})`);await saving;
 assert.equal(element('labVoteFeedback').textContent,'A/B 已盲化，不显示版本身份。','late response must not mark another sample as recorded');
 run(`labPost=async()=>({status:'ok'})`);await run(`labVote('tie')`);
 assert.equal(element('labVoteFeedback').textContent,'已记录：听感持平');

 run(`labData={status:{},job:{result:{status:'ok',run_id:'r2',rows:[{stem:'a',scene_id:'NPARK'},{stem:'b',scene_id:'OOFFICE'}],blind_pairs:[{stem:'a'},{stem:'b'}]}}};globalThis.opened=null;labOpen=p=>opened=p;labListenScene('OOFFICE')`);
 assert.equal(run('opened'),'loop');
 assert.deepEqual(JSON.parse(run('JSON.stringify(labSelectedPair)')),{run:'r2',stem:'b'});
 assert.match(run('labReview()'),/value="b" selected/);
 run(`labData.job.result.run_id='r3'`);
 assert.doesNotMatch(run('labReview()'),/value="b" selected/,'selection must not leak to another run');

 run(`globalThis.renders=0;globalThis.runUpdates=0;renderLab=()=>renders++;labRunStatus=()=>runUpdates++;labPage='run';fetch=async()=>({ok:true,json:async()=>({state:'idle'})})`);
 await run('labRefresh()');
 const data=run('JSON.stringify(labData)');
 assert.equal(run('renders'),1);
 run(`fetch=async()=>({ok:false})`);await run('labRefresh()');
 assert.equal(element('labConnection').hidden,false);
 assert.equal(element('labStart').disabled,true);
 assert.equal(run('JSON.stringify(labData)'),data,'outage must preserve the previous result');
 run(`fetch=async()=>({ok:true,json:async()=>({state:'idle'})})`);await run('labRefresh()');
 assert.equal(element('labConnection').hidden,true);
 assert.equal(run('renders'),2,'same-payload recovery must still redraw the stale state');
 assert.equal(run('runUpdates'),2);

 assert.equal(run('labNum(0)'),'0.000');
 assert.equal(run('labNum(null)'),'—');
 assert.equal(run('labNum(NaN)'),'—');
 const summary=run(`labSceneSummary([
  {scene_id:'NPARK',baseline_pq:6,candidate_pq:7},
  {scene_id:'NPARK',baseline_pq:8,candidate_pq:7},
  {scene_id:'OOFFICE',baseline_pq:5,candidate_pq:5.5}
 ])`);
 assert.match(summary,/安静 · 公园/);
 assert.match(summary,/>0\.000</);
 assert.match(summary,/1 \/ 2/);
 assert.match(summary,/办公室/);
 assert.doesNotMatch(summary,/咖啡厅/,'empty scenes stay out of the compact history summary');
 console.log('PASS: delayed listening feedback, scene/run selection isolation, offline retained data and recovery, zero vs missing');
})().catch(e=>{console.error(e);process.exitCode=1;});
