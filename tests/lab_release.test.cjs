// Regression fixtures only: no network, audio generation, or real experiment writes.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map();
const el=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',dataset:{},setAttribute(){},classList:{toggle(){}}});return elements.get(id)};
const c=vm.createContext({console,document:{getElementById:el,querySelector:()=>el('switch'),querySelectorAll:()=>[],addEventListener(){}},location:{hash:''},history:{pushState(){}},window:{scrollTo(){}},setInterval(){},fetch(){throw Error('Network forbidden')}});
vm.runInContext(fs.readFileSync('app/lab.js','utf8'),c);
const run=s=>vm.runInContext(s,c);
for(const rows of [
 [{baseline_pq:9,candidate_pq:null},{baseline_pq:1,candidate_pq:2}],
 [{baseline_pq:null,candidate_pq:9},{baseline_pq:0,candidate_pq:1}],
]){
 run(`globalThis.rows=${JSON.stringify(rows.map(r=>({scene_id:'OOFFICE',...r})))}`);
 const html=run('labSceneSummary(rows)');
 assert.match(html,/>\+1\.000</);assert.match(html,/1 \/ 2 · 1 条缺测/);assert.match(html,/0 \/ 1/);
 run(`labData={status:{},job:{state:'done',result:{status:'ok',baseline:'v1',candidate:'v2',rows}}};renderLab()`);
 assert.match(el('labCharts').innerHTML,/\+1\.000/);assert.doesNotMatch(el('labCharts').innerHTML,/-3\.000/);
}
for(const missing of [null,undefined,NaN,Infinity,'']){
 c.missing=missing;
 assert.match(run("labSceneSummary([{scene_id:'OOFFICE',baseline_pq:1,candidate_pq:missing}])"),/0 \/ 1 · 1 条缺测/);
 assert.equal(run("labReviewEntries({rows:[{stem:'a',baseline_pq:6,candidate_pq:missing}],blind_pairs:[{stem:'a'}]})[0].delta"),null);
}
assert.equal(run("labReviewEntries({rows:[{stem:'a',baseline_pq:0,candidate_pq:0}],blind_pairs:[{stem:'a'}]})[0].delta"),0);
assert.match(run("labSceneSummary([{scene_id:'OOFFICE',baseline_pq:0,candidate_pq:0}])"),/>0\.000</);
// Equal coordinate steps must project to equal lengths without rotation or a depth change.
run(`labVoiceRotation={yaw:0,pitch:0};labVoiceData={points:[{x:0,y:0,z:0},{x:1,y:0,z:0},{x:0,y:1,z:0},{x:10,y:2,z:3},{x:0,y:0,z:-3}].map((p,i)=>({...p,file:i+'.wav',name:'v'+i,cluster:0}))}`);
const svg=run('labVoiceScene()');
const point=i=>{const tag=svg.match(new RegExp('<circle class="voice-point[^>]*data-index="'+i+'"[^>]*>'))[0];return ['cx','cy'].map(k=>Number(tag.match(new RegExp(k+'="([^"]+)"'))[1]))};
assert.ok(Math.abs((point(1)[0]-point(0)[0])-(point(0)[1]-point(2)[1]))<.2,'same scale on all axes');
// Cluster focus must not reconstruct the selected player's container.
el('voiceSelection').innerHTML='existing player';
run('labFocusVoice(0)');assert.equal(el('voiceSelection').innerHTML,'existing player');
run('labFocusVoice(null)');assert.equal(el('voiceSelection').innerHTML,'existing player');
console.log('PASS: paired populations, missing vs zero, equal PCA scales, focus preserves audio container');
