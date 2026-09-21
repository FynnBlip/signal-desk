/* A readable entry to the existing laboratory. All measurements remain server-owned. */
const labModules = [
  ['corpus','01','语料选择','固定测试文本'],['voice','02','声线聚类','C1 · C2 · C3 · C4'],
  ['tts','03','TTS 合成','生成多种音色'],['channel','04','信道仿真','Opus × 六场景'],
  ['denoise','05','降噪版本','V1 → V4'],['evaluate','06','客观评测','AudioBox PQ'],
  ['loop','07','听审与迭代','人工确认 · 实验留痕']
];
const labScenes = [['NPARK','安静 · 公园',25,45],['OOFFICE','办公室',15,55],['PCAFETER','咖啡厅',10,70],['PRESTO','食堂',5,72],['STRAFFIC','路口 · 交通',0,75],['TMETRO','地铁 · 高噪',-10,90]];
let labData = null, labMode = 'round', labBusy = false, labSignature = '', labPage='lab', labPanelRequest=0, labConnectionError=false;
let labSubmitting=false,labRunUncertain=false,labPollEpoch=0;
const esc = s => String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labNum = n => typeof n==='number' && Number.isFinite(n) ? n.toFixed(3) : '—';
const labSigned = n => typeof n==='number' && Number.isFinite(n) ? `${n>0?'+':''}${n.toFixed(3)}` : '—';
function labOpen(view, page, record=true) {
  document.querySelectorAll('audio,video').forEach(a=>a.pause());
  labPage=page==='history'?'history':page==='run'?'run':view;
  document.getElementById('view-lab').hidden=labPage!=='lab';
  document.getElementById('labPanel').hidden=labPage==='lab';
  if(record && location.hash!==`#${labPage}`)history.pushState(null,'',`#${labPage}`);
  labMark(labPage.startsWith('detail-')?'lab':labPage);
  ++labPanelRequest;
  if(labPage!=='lab')labPanel(); else renderLab();
  window.scrollTo(0,0);
}
function labMark(view) {
  document.querySelectorAll('[data-lab-nav]').forEach(b=>{
    const on=b.dataset.labNav===view;
    b.classList.toggle('active',on);
    if(on)b.setAttribute('aria-current','page'); else b.removeAttribute('aria-current');
  });
}
function initLab() {
  document.body.classList.add('lab-shell');
  document.querySelector('.side-links').innerHTML = `<button class="nav-item" data-lab-nav="lab" onclick="labOpen('lab')">实验总览</button><p class="nav-label">通话评测流程</p>${labModules.map(([v,n,t,d])=>`<button class="nav-item lab-module" data-lab-nav="${v}" onclick="labOpen('${v}'${v==='loop'?",'conclusion'":''})"><span>${n}</span><span><b>${t}</b><small>${d}</small></span></button>`).join('')}<button class="nav-item" data-lab-nav="run" onclick="labOpen('loop','run')">配置与运行</button><button class="nav-item lab-history" data-lab-nav="history" onclick="labOpen('loop','history')">实验历史 ↗</button>`;
  const host=document.createElement('section'); host.id='view-lab'; host.hidden=true;
  host.innerHTML=`<header class="lab-heading"><div><p>音频实验室 / 通话质量</p><h1>听见每一版的变化。</h1><div class="lab-intro">同一段语料，不同的声音与噪声。比较降噪版本，让每次改进都有依据。</div></div><button class="lab-primary" onclick="labOpen('loop','run')">配置与运行 <span>↗</span></button></header>
  <div class="lab-route" aria-label="实验数据流"><button onclick="labOpen('corpus')">语料</button><i>→</i><button onclick="labOpen('tts')">TTS 音色</button><i>→</i><button onclick="labOpen('voice')">C1–C4 聚类</button><i>→</i><button onclick="labOpen('channel')">六场景信道</button><i>→</i><button onclick="labOpen('denoise')">降噪版本</button><i>→</i><button onclick="labOpen('evaluate')">PQ 评测</button><i>→</i><button onclick="labOpen('loop','conclusion')">听审 · 下一轮</button></div>
  <div id="labLive" class="lab-live" aria-live="polite">正在读取实验状态…</div>
  <section class="lab-architecture" aria-labelledby="labArchitectureTitle"><details id="labArchitectureDetails"><summary><img src="/assets/runtime-architecture.webp" alt="评测流程架构预览" width="240" height="143"><span><strong id="labArchitectureTitle">一次评测，如何跑完？</strong><span id="labArchitectureDescription">语料 → TTS → 声线 → 信道 → 降噪 → 评测 → 人工确认</span><span>展开动效 · 流程示意，非本机实时状态</span></span></summary><div class="lab-architecture-stage"><video id="labArchitectureVideo" controls muted playsinline preload="none" poster="/assets/runtime-architecture.webp" aria-describedby="labArchitectureDescription"><source src="/assets/runtime-architecture.webm" type="video/webm"></video></div><div class="lab-architecture-actions"><button id="labArchitectureReplay" class="lab-secondary" type="button">重播动效</button><a class="lab-secondary" href="/architecture.html" target="_blank" rel="noopener">查看交互架构 ↗</a><span id="labArchitectureFeedback" role="status"></span></div><p>首次准备语料、TTS 与声线分组；日常迭代复用缓存。视频为流程演示，不代表任务进度或当前 Provider 就绪数量。</p></details></section>
  <section class="lab-results"><div class="lab-section-head"><div><h2>每个场景，改善了吗？</h2><p id="labSource">正在读取结果来源…</p></div><div class="lab-switch" aria-label="比较数据来源"><button aria-pressed="true" onclick="labSwitch('round')">本轮比较</button><button aria-pressed="false" onclick="labSwitch('versions')">四版本基准</button></div></div><div id="labCharts" class="lab-charts"></div></section>
  <details class="lab-trace"><summary>运行记录 <span>Trace · 展开查看</span></summary><div id="labTrace"></div></details>`;
  document.querySelector('main').prepend(host);
  labArchitectureMotion();
  const connection=document.createElement('div');connection.id='labConnection';connection.hidden=true;connection.setAttribute('role','alert');document.querySelector('main').prepend(connection);
  labRefresh();
  setInterval(()=>{ if(!document.hidden){labRefresh();if(labPage==='tts')labPreparePoll();} },5000);
}
function labArchitectureMotion(){
  const video=document.getElementById('labArchitectureVideo'),replay=document.getElementById('labArchitectureReplay'),details=document.getElementById('labArchitectureDetails'),feedback=document.getElementById('labArchitectureFeedback');
  if(!video||!replay||!details)return;
  const reduced=window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const play=()=>{feedback.textContent='';video.play().catch(()=>{feedback.textContent='未能自动播放，请使用播放控件或查看交互架构。';});};
  replay.addEventListener('click',()=>{video.currentTime=0;play();});
  details.addEventListener('toggle',()=>{if(!details.open)video.pause();else if(!reduced)play();});
  video.addEventListener('error',()=>{feedback.textContent='视频加载失败，可打开交互架构查看完整流程。';});
}
async function labRefresh() {
  if(labBusy)return; labBusy=true;
  const epoch=labPollEpoch;
  try {
    const responses=await Promise.all(['/api/loop/status','/api/loop/job'].map(url=>fetch(url)));
    if(responses.some(r=>!r.ok))throw new Error('状态接口暂不可用');
    const [status,job]=await Promise.all(responses.map(r=>r.json()));
    if(epoch!==labPollEpoch)return;
    const previousResult=labResultSignature();
    labData={status,job};labRunUncertain=false;
    labConnectionError=false;document.getElementById('labConnection').hidden=true;
    const signature=JSON.stringify([status,job]);
    if(signature!==labSignature){labSignature=signature;renderLab();if(labPage==='run')labRunStatus();}
    if(previousResult!==labResultSignature()&&(labPage==='evaluate'||labPage==='loop'||labPage.startsWith('detail-')))await labPanel();
  } catch(e) {
    if(epoch!==labPollEpoch)return;
    labConnectionError=true;labSignature='';
    const connection=document.getElementById('labConnection');connection.hidden=false;
    connection.innerHTML=`<strong>暂时无法连接实验服务</strong><p>${esc(e.message)} · 已显示的数据暂未更新。</p><button class="lab-secondary" onclick="labRefresh()">重新连接</button>`;
    document.getElementById('labExecution').textContent='连接中断 · 状态暂未更新';
    if(!labData){document.getElementById('labLive').textContent='连接恢复后显示实验状态。';document.getElementById('labSource').textContent='结果暂不可用';}
    const start=document.getElementById('labStart');if(start)start.disabled=true;
  } finally {labBusy=false;if(epoch!==labPollEpoch)await labRefresh();}
}
function labSwitch(mode){labMode=mode;const url=new URL(location.href);url.searchParams.set('comparison',mode);history.replaceState(null,'',url);renderLab();}
function labResultSignature(){
  if(!labData)return '';
  const {status,job}=labData;
  return JSON.stringify([status.experiment_id,status.workspace_mode,status.baseline,status.candidate,job.state,labCurrent().result,status.version_summary]);
}
function labCurrent(){
  if(!labData)return {result:null,label:'正在读取实验状态'};
  const {status,job}=labData;
  if(status.workspace_mode==='blank')return {result:null,label:'新实验 · 尚无结果'};
  if(job.result?.status==='ok'&&(!job.result.experiment_id||job.result.experiment_id===status.experiment_id))return {result:job.result,label:'本轮结果 · 待人工确认'};
  const rounds=(status.rounds||[]).filter(r=>!status.experiment_id||r.experiment_id===status.experiment_id);
  const last=status.workspace_mode==='blank'?null:rounds.at(-1);
  return {result:last||null,label:last?`第 ${last.round} 轮 · 已归档结果`:'当前实验尚无已完成结果'};
}
function renderLab(){
  if(!labData)return;
  const {status,job}=labData,{result,label}=labCurrent();
  const judge=result?.judge||{}, baseline=String(result?.baseline||status.baseline||'—').toUpperCase(), candidate=String(result?.candidate||status.candidate||'—').toUpperCase();
  const running=job.state==='running';
  const indicator=document.getElementById('labExecution');if(indicator)indicator.textContent=running?`运行中 · ${job.done??0}/${job.total??0}`:job.result?.status==='ok'?'结果就绪 · 待人工复核':job.state==='error'?'本轮运行失败':'当前无运行任务';
  const archived=job.result?.status!=='ok' && Boolean(result);
  const action=result?.decision?.action;
  const title=running?'实验正在运行':job.state==='error'?'本轮运行未完成':!result?'从一次公平的比较开始':action==='accept'?`建议晋级 ${candidate}`:action==='accept_conditional'?`建议有条件晋级 ${candidate}`:action==='iterate'?`建议保留 ${baseline}`:'查看本轮判定';
  document.getElementById('labLive').innerHTML=`<div class="lab-verdict"><span>${esc(running?job.stage||'运行中':label)}</span><h2>${archived&&!running?'历史判定：':''}${esc(title)}</h2><p>${esc(running?job.message||'正在处理测试样本':result?`${baseline} → ${candidate} · 固定条件下比较`:'先准备音色与场景，再配置要比较的版本。')}</p></div><div class="lab-key"><span>${running?'已完成样本':'常规平均 ΔPQ'}</span><strong>${running?`${job.done??0} / ${job.total??'—'}`:labSigned(judge.regular_delta)}</strong></div><button class="lab-secondary" onclick="labOpen('loop','${running||!result?'run':archived?'history':'conclusion'}')">${running?'查看实时状态':archived?'查看历史判定':result?'进入复核':'开始配置'} →</button>`;
  const summary=status.version_summary||{};
  document.getElementById('labSource').textContent=labMode==='versions'?`四版本基准 · ${summary.shared_samples??0} 个共同样本${summary.status!=='ok'?' · 覆盖不足，暂不推荐版本':''}`:`${label} · ${result?.rows?.length??0} 个样本 · PQ 越高越好`;
  document.querySelectorAll('.lab-switch button').forEach((b,i)=>b.setAttribute('aria-pressed',String((i===0)===(labMode==='round'))));
  document.querySelector('.lab-switch button').textContent=archived?'最近已完成比较':'本轮比较';
  document.getElementById('labCharts').innerHTML=labScenes.map(([id,name,snr,level])=>{
    let versions,values,count,missing=0;
    if(labMode==='versions'){
      const scene=(summary.scenes||[]).find(s=>Number(s.snr_db)===snr);
      versions=['v1','v2','v3','v4'];values=versions.map(v=>scene?.scores?.[v]??null);count=null;
    }else{
      const allRows=(result?.rows||[]).filter(r=>r.scene_id===id);
      const rows=allRows.filter(r=>Number.isFinite(r.baseline_pq)&&Number.isFinite(r.candidate_pq));missing=allRows.length-rows.length;
      const mean=key=>{const v=rows.map(r=>r[key]).filter(v=>typeof v==='number'&&Number.isFinite(v));return v.length?v.reduce((a,b)=>a+b,0)/v.length:null;};
      versions=[baseline,candidate];values=[mean('baseline_pq'),mean('candidate_pq')];count=rows.length;
    }
    const delta=values.length===2&&values.every(v=>typeof v==='number')?values[1]-values[0]:null;
    return `<button class="lab-scene" data-scene="${id}" onclick="labInspect('${id}')"><div class="lab-scene-head"><h3>${name}</h3><span title="场景参考环境声级；仿真参数保留在实验明细中">约 ${level} dB</span></div>${labPlot(versions,values)}<div class="lab-scene-foot"><strong>${labMode==='round'?labSigned(delta):'查看版本表现'}</strong><span>${missing?`${count} 对有效 · ${missing} 条缺测`:count===0?'暂无样本':labMode==='round'?'新版 − 当前':'基准数据'} <b>↗</b></span></div></button>`;
  }).join('');
  const events=job.events||[];
  document.getElementById('labTrace').innerHTML=events.length?events.slice(-24).map(e=>`<div><time>${esc(e.time||e.at||e.timestamp||'')}</time><b>${esc(e.stage||e.title||e.type||'事件')}</b><span>${esc(e.message||e.detail||'')}</span></div>`).join(''):'<p>当前没有运行中的 Trace。历史实验的配置与判定保存在实验历史中。</p>';
}
function labPlot(versions,values){
  const points=values.map((v,i)=>({x:34+i*292/(values.length-1),y:164-(typeof v==='number'?Math.max(0,Math.min(10,v)):0)*14,v}));
  const valid=points.filter(p=>typeof p.v==='number'&&Number.isFinite(p.v));
  const line=valid.length===points.length?`<path class="lab-area" d="M${points[0].x},164 ${points.map(p=>`L${p.x},${p.y}`).join(' ')} L${points.at(-1).x},164 Z"/><polyline points="${points.map(p=>`${p.x},${p.y}`).join(' ')}"/>`:'';
  return `<svg viewBox="0 0 360 202" role="img" aria-label="${esc(versions.map((v,i)=>`${v}: ${labNum(values[i])}`).join('，'))}">${[0,5,10].map(v=>`<line x1="34" x2="326" y1="${164-v*14}" y2="${164-v*14}"/><text x="4" y="${168-v*14}" class="lab-axis">${v}</text>`).join('')}${line}${valid.map(p=>`<circle cx="${p.x}" cy="${p.y}" r="4"/><text x="${p.x}" y="${p.y-12}" text-anchor="middle" class="lab-value">${labNum(p.v)}</text>`).join('')}${versions.map((v,i)=>`<text x="${points[i].x}" y="193" text-anchor="middle">${esc(v.toUpperCase())}</text>`).join('')}${!valid.length?'<text x="180" y="98" text-anchor="middle">等待实验结果</text>':''}</svg>`;
}
function labInspect(id){labOpen('detail-'+id);}
async function labGet(url){const r=await fetch(url);if(!r.ok)throw new Error(`读取失败 (${r.status})`);return r.json();}
async function labPost(url,payload){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();if(!r.ok||d.status==='error')throw new Error(d.message||d.detail||'操作未完成');return d;}
function labPanelHead(title,description){return `<header class="lab-heading"><div><p>通话评测流程</p><h1>${title}</h1><div class="lab-intro">${description}</div></div><button class="lab-secondary" onclick="labOpen('lab')">返回实验总览</button></header>`;}
async function labPanel(){
  const request=++labPanelRequest, panel=document.getElementById('labPanel');
  const mod=labModules.find(m=>m[0]===labPage);
  panel.innerHTML=labPanelHead(mod?mod[2]:labPage==='run'?'配置与运行':'实验历史','正在读取本地数据…');
  try{
    if(!labData){const [status,job]=await Promise.all(['/api/loop/status','/api/loop/job'].map(labGet));labData={status,job};}
    if(labPage.startsWith('detail-')){if(request===labPanelRequest)labSceneDetail(labPage.slice(7));return;}
    let content='',description='';const page=labPage;
    if(page==='corpus'){
      const [d,cache]=await Promise.all([labGet('/api/corpus/templates'),labGet('/api/voice/cohorts')]);const active=cache.cohorts.find(c=>c.active);description='先固定考题，再比较音色、噪声与降噪算法。';
      content=`<section class="lab-explain"><h2>当前固定探针</h2><p class="lab-probe">${esc(active?.probe_text||'尚未选择测试音色集，暂无固定探针。')}</p></section><button class="lab-primary" onclick="labOpen('tts')">查看测试音色 →</button><details class="lab-explain"><summary>其他语料模板 · ${d.templates.length} 条</summary><div class="lab-prose-list">${d.templates.map(t=>`<article><span>${esc(t.id)} · ${esc(t.scene)}</span><p>${esc(t.text)}</p></article>`).join('')}</div></details>`;
    }else if(page==='voice'){
      const cache=await labGet('/api/voice/cohorts');
      labCohorts=cache.cohorts||[];
      const chosen=labCohorts.find(c=>c.id===labChosenCohort)||labCohorts.find(c=>c.active);
      labChosenCohort=chosen?.id||null;
      let d;
      if(chosen&&!chosen.active){
        d=chosen.clustered?await labGet(`/api/voice/cohorts/${encodeURIComponent(chosen.id)}/distribution`):{cohort_id:chosen.id,points:[]};
      }else d=await labGet('/api/voice/distribution');
      if(request!==labPanelRequest)return;
      if(labVoiceCohort!==d.cohort_id){labVoiceFilter=null;labVoiceSelection=null;}
      labVoiceCohort=d.cohort_id;labVoiceData=d;
      description='每个点是一种真实音色。旋转声学向量空间，观察簇的结构，再点选音色试听。';
      content=labCohortControls(chosen)+`<div id="labVoiceMap"></div><button class="lab-primary" onclick="labOpen('channel')">下一步：六场景信道 →</button>`;
    }else if(page==='tts'){
      const [d,job,providers]=await Promise.all([labGet('/api/voice/cohorts'),labGet('/api/voice/cohorts/job'),labGet('/api/providers')]);description='同一段文本，多种音色。当前流程优先复用已生成的测试音频。';
      if(request!==labPanelRequest)return;
      labCohorts=d.cohorts||[];labPrepareJob=job;labTTSProvider=(providers.providers||[]).find(p=>p.id==='minimax-speech-2.8-turbo');
      const active=labCohorts.find(c=>c.active);
      content=`<section class="lab-explain"><span>当前测试集</span><h2>${esc(active?.name||'尚未选择测试集')}</h2><div class="lab-clusters"><article><strong>${active?.completed_count??0}</strong><p>已缓存音色</p></article><article><strong>${active?.n_clusters??0}</strong><p>声线簇</p></article></div><p>${esc(active?active.provider+' · '+active.model:'准备音频缓存后再进行评测。')}</p></section><button class="lab-primary" onclick="labOpen('voice')">查看声线分布 →</button>`;
      content+=`<section class="lab-explain"><h2>准备测试音色</h2><p>优先选择已有缓存；新的生成请求只在预览并确认后发送。</p><div id="labCohortCache"></div><details id="labPrepareDetails" ${active?'':'open'}><summary>准备一组新音色 · 26 音色 / C1–C4</summary><form id="labPrepareForm" onsubmit="labPreviewPrepare(event)"><label>资源标签<input id="labPrepareLabel" maxlength="80" required oninput="labRememberPrepareLabel(this.value)" value="${esc(labPrepareLabel)}" placeholder="例如：普通话参考音色"></label><p>普通话系统音色 · seed 42 · 使用服务端默认固定探针</p><button class="lab-secondary" id="labPreparePreview">预览调用量</button></form></details><p id="labPrepareFeedback" role="status">${esc(labPrepareMessage)}</p><div id="labPrepareJob" role="status"></div><p><a href="/setup.html#voice">音色、噪声与模型准备指南 ↗</a></p></section>`;
    }else if(page==='channel'){
      const noise=await labGet('/api/channel/noise/scenes');
      description='干净语音经过噪声与 Opus 编解码，再交给降噪算法。颜色始终对应同一场景。';
      content=`<div class="lab-charts">${noise.scenes.map(({id,label,level_db,preview,preview_ready})=>`<article class="lab-noise" data-scene="${esc(id)}"><h2>${esc(label)}</h2><strong>约 ${level_db}<small> dB · 参考环境声级</small></strong>${preview_ready?labNoisePlayer(id,label,preview):'<p>噪声预览尚未准备</p>'}</article>`).join('')}</div><div class="lab-explain"><h2>固定信道，再比较版本</h2><p>固定基准使用 Opus 宽带 16 kHz、16 kbps VBR，随机种子 42。六场景使用相同音色；信道输出再交给每个降噪版本。</p><p>环境声级仅作场景参考，不是播放音量的实测值；实际噪声注入以实验记录的 SNR 为准。</p></div><button class="lab-primary" onclick="labOpen('denoise')">下一步：降噪版本 →</button>`;
    }else if(page==='denoise'){
      const d=await labGet('/api/loop/options');description='改变降噪版本，固定其余条件。每次对比留下配置、评分与判定。';
      content=`<div class="lab-clusters">${(d.versions||[]).map(v=>`<article><h2>${esc(v.id.toUpperCase())}</h2><p>${esc(v.label)}</p></article>`).join('')}</div><button class="lab-primary" onclick="labOpen('loop','run')">选择比较版本 →</button>`;
    }else if(page==='evaluate'){
      description='AudioBox PQ 为主要客观指标。先看六场景变化，再检查 Gate 与原始评分。';
      const {result}=labCurrent();const j=result?.judge||{};
      content=`<p>${esc(labCurrent().label)}</p><div class="lab-clusters"><article><h2>当前版本</h2><strong>${labNum(j.baseline_regular_pq)}</strong></article><article><h2>候选版本</h2><strong>${labNum(j.candidate_regular_pq)}</strong></article><article><h2>平均 ΔPQ</h2><strong>${labSigned(j.regular_delta)}</strong></article></div><div class="lab-prose-list">${(j.gate_checks||[]).map(g=>`<article><span>${g.pass?'通过':'未通过'}</span><h2>${esc(g.label)}</h2><p>${esc(g.actual)} · 要求 ${esc(g.threshold)}</p></article>`).join('')}</div><button class="lab-primary" onclick="labOpen('lab')">查看六场景图 →</button>`;
    }else if(page==='run'){
      const d=await labGet('/api/loop/options');labOptions=d;description='复用测试音频，在相同条件下比较两个版本。';const s=labData.status;
      const baseline=s.baseline||d.versions[0]?.id;
      content=`<div class="lab-preflight">${Object.entries(s.benchmark?.readiness||{}).map(([k,v])=>`<span class="${v?'ready':'missing'}">${v?'✓':'○'} ${{voice:'音色缓存',noise:'六场景噪声',dut:'降噪版本',evaluator:'PQ 评测'}[k]||esc(k)}</span>`).join('')}</div><form id="labRunForm" onsubmit="labSubmitRun(event)"><div class="lab-form-row"><label>当前基准<select id="labBaseline" onchange="labCandidates()" ${s.baseline?'disabled':''}>${d.versions.map(v=>`<option value="${esc(v.id)}" ${v.id===baseline?'selected':''}>${esc(v.label)}</option>`).join('')}</select></label><span>→</span><label>候选版本<select id="labCandidate">${d.versions.filter(v=>v.id!==baseline).map(v=>`<option value="${esc(v.id)}" ${v.id===s.candidate?'selected':''}>${esc(v.label)}</option>`).join('')}</select></label></div><details class="lab-explain"><summary>本轮固定条件</summary><p>${esc(s.benchmark?.voice_set)} · ${esc(s.benchmark?.scene_set)}</p><p>${esc(s.benchmark?.evaluator)}</p><p>沿用当前配置，缓存命中时直接复用。运行可能调用判定模型，不重新生成 TTS。</p></details><div class="lab-actions"><button class="lab-primary" id="labStart">保存配置并运行</button><button type="button" class="lab-secondary" onclick="labNewDialog()">新建实验</button></div><p id="labRunFeedback" role="status"></p></form><section id="labRunStatus" class="lab-explain"></section>`;
    }else if(page==='history'){
      description='按实验查看确认过的结果。展开一轮，查看判定依据与场景评分。';
      const archive=await labGet('/api/loop/archive');const seen=new Set();labHistory=[...(labData.status.rounds||[]),...(archive.rounds||[])].filter(r=>{const key=[r.experiment_id,r.round,r.time].join('|');if(seen.has(key))return false;seen.add(key);return true;}).sort((a,b)=>String(b.time).localeCompare(String(a.time)));
      content=`<div class="lab-actions"><button class="lab-secondary" onclick="labReport()">查看实验报告</button></div><div class="lab-prose-list">${labHistory.map((r,i)=>`<details class="lab-history-round"><summary>第 ${esc(r.round)} 轮 · ${esc(r.baseline)} → ${esc(r.candidate)} <span>${esc(r.time)} · ΔPQ ${labSigned(r.judge?.regular_delta)}</span></summary><p>${esc(r.decision?.reason||labActionLabel(r.decision?.action))}</p>${labSceneSummary(r.rows||[])}<details class="lab-raw-evidence"><summary>查看 ${r.rows?.length??0} 条逐样本证据</summary>${labRowsTable(r.rows||[])}</details></details>`).join('')||'<p>还没有已确认的实验。</p>'}</div>`;
    }else if(page==='loop'){
      description='先听 A/B 差异，再结合工程 Gate 决定是否采用本轮建议。';content=labReview();
    }
    if(request!==labPanelRequest)return;
    panel.innerHTML=labPanelHead(mod?mod[2]:page==='run'?'配置与运行':'实验历史',description)+content;
    if(page==='run')labRunStatus();
    if(page==='voice')labRenderVoice();
    if(page==='tts'){labRenderCohortCache();labPrepareStatus();}
    if(page==='loop')labPair();
  }catch(e){if(request===labPanelRequest)panel.innerHTML=labPanelHead(mod?mod[2]:labPage==='run'?'配置与运行':labPage.startsWith('detail-')?'场景详情':'实验历史','数据暂时无法读取，请重试。')+`<p role="alert">${esc(e.message)}</p><button class="lab-secondary" onclick="labPanel()">重新读取</button>`;}
}
// Resource preparation uses the existing Cohort APIs; no generation on page entry.
let labCohorts=[],labChosenCohort=null,labTTSProvider=null,labPrepareJob={state:'idle'},labPrepareBusy=false,labPreparePolling=false,labPrepareUncertain=false,labPrepareEpoch=0,labPrepareLabel='',labPrepareMessage='',labPrepareReadError='';
function labRememberPrepareLabel(value){labPrepareLabel=value;}
function labCohortReady(c){return c?.status==='ready'&&c.completed_count===26&&c.requested_count===26;}
function labChooseCohort(id){if(labPrepareBusy)return;labChosenCohort=id;labOpen('voice');}
function labRenderCohortCache(){
 const host=document.getElementById('labCohortCache');if(!host)return;
 const folded=labCohorts.some(c=>c.active)&&!labPrepareJob.cohort_id;
 host.innerHTML=labCohorts.length?`${folded?'<details><summary>选择其他已有缓存 · '+labCohorts.length+' 组</summary>':''}<div class="lab-prose-list">${labCohorts.map((c,i)=>`<article><h2>${esc(c.name)}</h2><p>${c.completed_count??0} / ${c.requested_count??0} 个音色 · ${esc(c.id)} · ${c.active?'当前声线参考集':c.clustered?'已聚类':'尚未聚类'} · ${esc(c.status)}</p><div class="lab-actions"><button class="lab-secondary" data-prepare-control onclick="labChooseCohort(labCohorts[${i}].id)">选择缓存，查看声线</button>${c.requested_count===26&&['partial','error','cancelled'].includes(c.status)?`<button class="lab-secondary" data-prepare-control onclick="labPreviewPrepare(null,${i})">预览续跑</button>`:''}</div></article>`).join('')}</div>${folded?'</details>':''}`:'<p>尚无音色缓存，请先预览并准备测试音色。</p>';
}
function labCohortControls(c){
 return `<section class="voice-resource"><label>声线资源<select id="labCohortSelect" onchange="labChooseCohort(this.value)" ${labPrepareBusy?'disabled':''}>${labCohorts.map(item=>`<option value="${esc(item.id)}" ${item.id===c?.id?'selected':''}>${esc(item.name)} · ${esc(item.id)}${item.active?' · 当前参考集':''}</option>`).join('')||'<option>尚无音色缓存</option>'}</select></label><p class="voice-resource-state">${c?`${c.completed_count??0} / ${c.requested_count??0} 个音色 · ${c.active?'已锁定声线参考集':c.clustered?`已聚类 · ${c.n_clusters??'—'} 簇`:'尚未聚类'}`:'请先到 TTS 页准备音色。'}。</p><details ${c?.active?'':'open'}><summary>参考集设置与资源详情</summary><p>资源 ID：${esc(c?.id||'—')} · 声线资源与降噪基准版本分别管理。</p><div class="lab-actions"><button class="lab-secondary" data-prepare-control onclick="labAnalyzeCohort()" ${!labCohortReady(c)||labPrepareBusy?'disabled':''}>四簇聚类</button><button class="lab-primary" data-prepare-control onclick="labActivateCohort()" ${!labCohortReady(c)||!c.can_activate||c.n_clusters!==4||c.active||labPrepareBusy?'disabled':''}>锁为声线参考集</button><button class="lab-secondary" onclick="labOpen('tts')">准备 / 补齐音色 →</button>${c?.active?'<button class="lab-secondary" onclick="labOpen(\'run\')">进入配置与运行 →</button>':''}</div></details><p id="labPrepareFeedback" role="status">${esc(labPrepareMessage)}</p></section>`;
}
function labPrepareStatus(){
 const job=labPrepareJob,host=document.getElementById('labPrepareJob');
 if(host)host.innerHTML=`<h2>${{idle:'尚未启动生成',running:'正在准备音色',done:'音色已就绪',partial:'部分完成，请补齐',error:'生成失败',cancelled:'已暂停，缓存保留'}[job.state]||'状态未知'}</h2><p>${esc(job.message)}</p>${job.total?`<progress max="${Number(job.total)}" value="${Number(job.done)||0}"></progress><p>${job.done??0} / ${job.total} 个音色</p>`:''}${job.state==='running'?'<button class="lab-secondary" data-prepare-control onclick="labPausePrepare()">请求暂停</button>':''}`;
 const locked=labPrepareBusy||labPrepareUncertain||job.state==='running';
 ['labPreparePreview','labPrepareLabel'].forEach(id=>{const el=document.getElementById(id);if(el)el.disabled=locked||labTTSProvider?.ready!==true;});
 document.querySelectorAll('#labCohortCache [data-prepare-control]').forEach(b=>b.disabled=locked);
 const feedback=document.getElementById('labPrepareFeedback');if(feedback)feedback.textContent=labPrepareReadError||labPrepareMessage||(labTTSProvider?.ready===true?'':'MiniMax Provider 尚未就绪；已有缓存仍可查看和聚类，请检查准备指南。');
}
async function labPreparePoll(){
 if(labPreparePolling||labPrepareBusy||labPage!=='tts')return;labPreparePolling=true;const epoch=labPrepareEpoch;
 try{const job=await labGet('/api/voice/cohorts/job');if(labPage!=='tts'||epoch!==labPrepareEpoch||labPrepareBusy)return;const changed=JSON.stringify(job)!==JSON.stringify(labPrepareJob);labPrepareJob=job;labPrepareUncertain=false;labPrepareReadError='';labPrepareStatus();if(changed&&job.state!=='running'){const cache=await labGet('/api/voice/cohorts');if(labPage==='tts'&&epoch===labPrepareEpoch){labCohorts=cache.cohorts||[];labRenderCohortCache();labPrepareStatus();}}}
 catch(e){labPrepareReadError=`生成状态暂未更新：${e.message}。不会自动重发生成请求。`;if(labPage==='tts')labPrepareStatus();}
 finally{labPreparePolling=false;}
}
async function labPreviewPrepare(event,index){
 event?.preventDefault();if(labPrepareBusy||labPrepareUncertain||labPrepareJob.state==='running')return;
 if(event)labPrepareLabel=document.getElementById('labPrepareLabel').value;
 const cached=index===undefined?null:labCohorts[index];
 const payload={benchmark:true,count:26,seed:cached?.seed??42,language_scope:cached?.language_scope||'mandarin',kinds:['system'],version_label:cached?.version_label||(cached?'续跑 · '+cached.id:labPrepareLabel.trim())};
 if(cached){payload.cohort_id=cached.id;payload.probe_text=cached.probe_text;}
 if(!payload.version_label){labPrepareMessage='请填写可读的资源标签。';labPrepareStatus();return;}
 if(labTTSProvider?.ready!==true){labPrepareMessage='MiniMax Provider 尚未就绪，请检查准备指南。';labPrepareStatus();return;}
 labPrepareBusy=true;labPrepareMessage='正在预览调用量，不生成音频…';labPrepareStatus();
 try{
  const plan=await labPost('/api/voice/cohorts/plan',payload);if(plan.selected_count!==26)throw new Error('固定参考集需要 26 个不同音色；目录不足，未启动生成。');
  if(labPage!=='tts')return;
  labDialog(cached?'确认补齐音色':'确认准备音色',`<p>${esc(labTTSProvider.name)} · ${esc(plan.version_label)}</p><p>26 个音色；最多 ${esc(plan.api_calls)} 次生成调用，实际以缓存复用和服务反馈为准，不是精确费用。</p>${cached?`<p>续用 ${esc(cached.name)}；已有完整缓存保留，只补缺失样本。</p>`:''}<p>${esc(plan.probe_text)}</p><details><summary>查看所选音色</summary><p>${(plan.voices||[]).map(v=>esc(v.name||v.voice_id)).join('、')}</p></details><p>确认后可能产生真实 API 费用。离开页面不会取消，暂停会在当前音色请求结束后生效。</p>`,()=>labStartPrepare({...payload,probe_text:plan.probe_text},cached?.id));
  labPrepareMessage='预览完成；取消不会发送生成请求。';
 }catch(e){labPrepareMessage=e.message;}
 finally{labPrepareBusy=false;if(labPage==='tts')labPrepareStatus();}
}
async function labStartPrepare(payload,cohort){
 if(labPrepareBusy||labPrepareUncertain||labPrepareJob.state==='running')throw new Error('已有资源操作正在进行或请求状态待核对。');
 labPrepareBusy=true;++labPrepareEpoch;labPrepareMessage='正在提交生成请求…';labPrepareStatus();
 try{const result=await labPost('/api/voice/cohorts/run',payload);labChosenCohort=result.cohort_id||cohort;labPrepareJob=result.status==='reused'?{state:'done',message:result.message,cohort_id:labChosenCohort}:{state:'running',message:'生成请求已受理',done:0,total:26,cohort_id:labChosenCohort};labPrepareMessage=result.message||'生成请求已受理；请查看实际进度。';}
 catch(e){labPrepareUncertain=true;labPrepareMessage=`请求未确认：${e.message}。请先刷新任务状态，不会自动重发。`;throw e;}
 finally{labPrepareBusy=false;if(labPage==='tts'){labPrepareStatus();await labPreparePoll();}}
}
async function labPausePrepare(){
 if(labPrepareBusy)return;labPrepareBusy=true;
 try{const r=await labPost('/api/voice/cohorts/cancel',{});labPrepareMessage=r.message||'已请求暂停；当前音色结束后停止，已成功缓存保留。';}
 catch(e){labPrepareMessage=e.message;}
 finally{labPrepareBusy=false;if(labPage==='tts'){labPrepareStatus();await labPreparePoll();}}
}
function labAnalyzeCohort(){
 const c=labCohorts.find(c=>c.id===labChosenCohort);if(labPrepareBusy||!labCohortReady(c))return;
 labDialog('确认四簇聚类',`<p>${esc(c.name)} · 26 个音色。沿用现有 C1–C4 分类与已有参考集映射，不生成 TTS。</p>`,()=>labCohortAction(c,'analyze',{k:4,use_anchor:true}));
}
function labActivateCohort(){
 const c=labCohorts.find(c=>c.id===labChosenCohort);if(labPrepareBusy||!labCohortReady(c)||!c.can_activate||c.n_clusters!==4||c.active)return;
 labDialog('锁为声线参考集',`<p>${esc(c.name)} 将成为声线资源参考集。服务端仍会检查 26 个完整且不同音色和四簇覆盖。</p><p>不会晋级降噪版本；噪声与模型仍需分别就绪。</p>`,()=>labCohortAction(c,'activate',{}));
}
async function labCohortAction(c,action,payload){
 if(labPrepareBusy)throw new Error('已有资源操作正在进行。');labPrepareBusy=true;labPrepareMessage=action==='analyze'?'正在计算四簇，请等待实际结果…':'正在校验并锁定声线参考集…';
 document.querySelectorAll('[data-prepare-control],#labCohortSelect').forEach(b=>b.disabled=true);
 const feedback=document.getElementById('labPrepareFeedback');if(feedback)feedback.textContent=labPrepareMessage;
 try{await labPost(`/api/voice/cohorts/${encodeURIComponent(c.id)}/${action}`,payload);labPrepareMessage=action==='analyze'?'四簇聚类完成；请检查分布后锁定声线参考集。':'声线参考集已锁定；其它噪声/模型缺项仍会阻断运行。';++labPollEpoch;await labRefresh();}
 catch(e){labPrepareMessage=`操作失败：${e.message}`;throw e;}
 finally{labPrepareBusy=false;if(labPage==='voice')await labPanel();}
}
function labRunStatus(){
 const host=document.getElementById('labRunStatus');if(!host||!labData)return;
 const j=labData.job,ready=labData.status.benchmark,pending=j.result?.status==='ok';
 host.innerHTML=`<h2>${{idle:'等待开始',running:'正在评测',done:'结果已生成',error:'运行失败',cancelled:'已取消'}[j.state]||'正在读取状态'}</h2><p>${esc(j.message)}</p>${ready&&!ready.ready?`<p>运行前需准备：${esc((ready.blockers||[]).join('；'))}</p><button class="lab-secondary" onclick="labOpen('tts')">检查音频缓存与测试集 →</button>`:''}${j.total?`<progress max="${Number(j.total)}" value="${Number(j.done)||0}"></progress><p>${j.done??0} / ${j.total} 个样本</p>`:''}${j.state==='running'?'<button class="lab-secondary" onclick="labCancel()">停止本轮</button>':''}${pending?`<button class="lab-primary" onclick="labOpen('loop')">结果已就绪，进入试听复核 →</button>`:''}<details class="lab-trace" open><summary>实时 Trace</summary><div>${(j.events||[]).slice(-24).map(e=>`<p><time>${esc(e.time||e.at||'')}</time> ${esc(e.message||e.title||e.stage||'事件')}</p>`).join('')||'<p>启动后，这里会显示每一步的处理状态。</p>'}</div></details>`;
 const button=document.getElementById('labStart');if(button)button.disabled=labSubmitting||labRunUncertain||labConnectionError||j.state==='running'||pending||Boolean(ready&&!ready.ready);
 const baseline=document.getElementById('labBaseline'),candidate=document.getElementById('labCandidate');
 if(baseline)baseline.disabled=labSubmitting||Boolean(labData.status.baseline);
 if(candidate)candidate.disabled=labSubmitting||j.state==='running'||pending;
 document.querySelectorAll('#labRunForm button[type="button"]').forEach(b=>b.disabled=labSubmitting);
}
async function labSubmitRun(event){
 event.preventDefault();if(labSubmitting||labRunUncertain)return;
 const feedback=document.getElementById('labRunFeedback'),baseline=document.getElementById('labBaseline').value,candidate=document.getElementById('labCandidate').value;
 const experiment=labData?.status.experiment_id,config=labData?.status.config,needsBaseline=!labData?.status.baseline;
 const sameExperiment=()=>labData?.status.experiment_id===experiment;
 const notify=text=>{if(sameExperiment()&&document.getElementById('labRunFeedback')===feedback)feedback.textContent=text;};
 let runRequested=false;labSubmitting=true;labRunStatus();
 try{
  if(labConnectionError)throw new Error('连接尚未恢复，请重新连接后运行');
  if(baseline===candidate)throw new Error('请选择不同的版本');
  if(labData.job.state==='running')throw new Error('已有任务正在运行');
  if(labData.job.result)throw new Error('先在听审页确认或放弃待复核结果，再运行下一轮');
  if(needsBaseline)await labPost('/api/loop/baseline',{version:baseline});
  if(!sameExperiment())throw new Error('实验已变化，请重新检查配置');
  await labPost('/api/loop/config',{config,baseline,candidate});
  if(!sameExperiment())throw new Error('实验已变化，请重新检查配置');
  runRequested=true;const started=await labPost('/api/loop/run',{});
  ++labPollEpoch;
  if(sameExperiment()){labData.job={state:'running',run_id:started.run_id,result:null};notify(`实验已启动 · ${baseline} → ${candidate}`);}
  await labRefresh();
 }catch(e){
  labRunUncertain=runRequested;notify(e.message+(runRequested?' · 请核对运行状态后再重试':''));
  if(runRequested)await labRefresh();
 }finally{labSubmitting=false;labRunStatus();}
}
function labSceneDetail(id){
 const scene=labScenes.find(s=>s[0]===id);if(!scene)return;
 const [,name,snr]=scene,{result,label}=labCurrent();let content;
 if(labMode==='versions'){
  const data=(labData.status.version_summary?.scenes||[]).find(s=>Number(s.snr_db)===snr);
  content=`<p>四版本基准 · 数据覆盖不足时不作推荐</p><div class="lab-clusters">${['v1','v2','v3','v4'].map(v=>`<article><h2>${v.toUpperCase()}</h2><strong>${labNum(data?.scores?.[v])}</strong></article>`).join('')}</div>`;
 }else{const rows=(result?.rows||[]).filter(r=>r.scene_id===id);content=rows.length?labRowsTable(rows):'<p>此实验还没有该场景的样本。</p>';if(labData.job.result?.blind_pairs?.some(p=>rows.some(r=>r.stem===p.stem)))content+=`<button class="lab-primary" onclick="labListenScene('${id}')">试听本轮 A/B →</button>`;}
 document.getElementById('labPanel').innerHTML=labPanelHead(name,labMode==='versions'?'四版本基准':label)+content;
}
let labVoiceData={points:[]},labVoiceFilter=null,labVoiceSelection=null,labVoiceCohort,labVoiceDrag=null;
let labVoiceRotation={yaw:-34,pitch:18};
const labClusterColors=['#20866b','#3876ce','#ca7c35','#8859bf'];
function labVoiceScene(){
 const points=labVoiceData.points.map((p,index)=>({...p,index})).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&Number.isFinite(p.z));
 if(!points.length)return '';
 const bounds=key=>{const values=points.map(p=>p[key]),min=Math.min(...values),max=Math.max(...values),pad=Math.max((max-min)*.08,.001);return [min-pad,max+pad];};
 const ranges={x:bounds('x'),y:bounds('y'),z:bounds('z')};
 const scale=Math.max(...Object.values(ranges).map(([min,max])=>max-min))/2;
 const norm=(value,key)=>(value-(ranges[key][0]+ranges[key][1])/2)/scale;
 const yaw=labVoiceRotation.yaw*Math.PI/180,pitch=labVoiceRotation.pitch*Math.PI/180;
 const project=([x,y,z])=>{const x1=x*Math.cos(yaw)-z*Math.sin(yaw),z1=x*Math.sin(yaw)+z*Math.cos(yaw),y1=y*Math.cos(pitch)-z1*Math.sin(pitch),z2=y*Math.sin(pitch)+z1*Math.cos(pitch),perspective=1+z2*.08;return {x:410+x1*178*perspective,y:258-y1*178*perspective,z:z2};};
 const clusters=[...new Set(points.map(p=>p.cluster))].sort((a,b)=>a-b);
 const prepared=points.map(p=>({...p,n:[norm(p.x,'x'),norm(p.y,'y'),norm(p.z,'z')]}));
 const centers=new Map(clusters.map(cluster=>{const members=prepared.filter(p=>p.cluster===cluster),n=[0,1,2].map(axis=>members.reduce((sum,p)=>sum+p.n[axis],0)/members.length);return [cluster,{n,p:project(n)}];}));
 const edgePairs=[[0,1],[0,2],[0,4],[1,3],[1,5],[2,3],[2,6],[3,7],[4,5],[4,6],[5,7],[6,7]],corners=[];
 for(const x of [-1,1])for(const y of [-1,1])for(const z of [-1,1])corners.push([x,y,z]);
 const line=(a,b,cls)=>{const p1=project(a),p2=project(b);return `<line class="${cls}" x1="${p1.x.toFixed(1)}" y1="${p1.y.toFixed(1)}" x2="${p2.x.toFixed(1)}" y2="${p2.y.toFixed(1)}"/>`;};
 const grid=[-.5,0,.5].map(t=>line([t,-1,-1],[t,-1,1],'voice-grid')+line([-1,-1,t],[1,-1,t],'voice-grid')+line([-1,t,-1],[1,t,-1],'voice-grid')).join('');
 const box=edgePairs.map(([a,b])=>line(corners[a],corners[b],'voice-box')).join('');
 const spokes=prepared.map(p=>{const point=project(p.n),center=centers.get(p.cluster).p,active=labVoiceFilter===null||labVoiceFilter===p.cluster;return `<line class="voice-spoke" x1="${center.x.toFixed(1)}" y1="${center.y.toFixed(1)}" x2="${point.x.toFixed(1)}" y2="${point.y.toFixed(1)}" stroke="${labClusterColors[p.cluster%4]}" opacity="${active?'.28':'.025'}"/>`;}).join('');
 const dots=prepared.map(p=>({...p,screen:project(p.n)})).sort((a,b)=>a.screen.z-b.screen.z).map(p=>{const active=labVoiceFilter===null||labVoiceFilter===p.cluster,selected=p.file===labVoiceSelection,r=6.2+(p.screen.z+2)*.65,opacity=active?Math.max(.58,Math.min(.98,.78+p.screen.z*.08)):.08,color=labClusterColors[p.cluster%4];return `<g><circle class="voice-point-halo" cx="${p.screen.x.toFixed(1)}" cy="${p.screen.y.toFixed(1)}" r="${(r+7).toFixed(1)}" fill="${color}" opacity="${active?'.10':'0'}"/><circle class="voice-point${selected?' selected':''}" data-index="${p.index}" role="button" tabindex="${active?'0':'-1'}" aria-label="${esc(p.name)}，C${p.cluster+1}，F0 ${Math.round(p.f0_mean)} Hz，F1 ${Math.round(p.f1_mean)} Hz，F2 ${Math.round(p.f2_mean)} Hz" aria-pressed="${selected}" cx="${p.screen.x.toFixed(1)}" cy="${p.screen.y.toFixed(1)}" r="${r.toFixed(1)}" fill="${color}" opacity="${opacity.toFixed(2)}" onclick="labSelectVoice(${p.index})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();labSelectVoice(${p.index})}"><title>${esc(p.name)} · C${p.cluster+1}</title></circle></g>`;}).join('');
 const centroids=clusters.map(cluster=>{const center=centers.get(cluster).p,active=labVoiceFilter===null||labVoiceFilter===cluster,color=labClusterColors[cluster%4];return `<g class="voice-centroid" opacity="${active?'1':'.12'}"><circle cx="${center.x.toFixed(1)}" cy="${center.y.toFixed(1)}" r="14" stroke="${color}"/><text x="${center.x.toFixed(1)}" y="${(center.y+4).toFixed(1)}" text-anchor="middle">C${cluster+1}</text></g>`;}).join('');
 const origin=[-1,-1,-1],axes=[[[1.18,-1,-1],'PC1'],[[-1,1.18,-1],'PC2'],[[-1,-1,1.18],'PC3']];
 const axisMarkup=axes.map(([end,label])=>{const p=project(end);return line(origin,end,'voice-axis')+`<text class="voice-axis-label" x="${p.x.toFixed(1)}" y="${p.y.toFixed(1)}">${label}</text>`;}).join('');
 return `${grid}${box}${axisMarkup}${spokes}${dots}${centroids}`;
}
function labRenderVoice(){
 const host=document.getElementById('labVoiceMap');if(!host)return;
 const points=labVoiceData.points.filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&Number.isFinite(p.z));
 if(!points.length){host.innerHTML='<p>还没有可展示的声学特征。准备音频并完成聚类后再来查看。</p>';return;}
 const clusters=[...new Set(points.map(p=>p.cluster))].sort();
 if(!clusters.includes(labVoiceFilter))labVoiceFilter=null;
 const embedding=labVoiceData.embedding||{},variance=(embedding.explained_variance||[]).reduce((sum,value)=>sum+Number(value||0),0);
 host.innerHTML=`<div class="voice-map-head"><div><h2>声学向量空间</h2><p>${points.length} 个音色 · ${embedding.source_dimensions||21} 维声学特征的 PCA 三维投影${variance?` · 解释方差 ${(variance*100).toFixed(0)}%`:''}</p></div><div class="voice-map-actions"><span>拖动旋转 · 点选试听</span><button class="lab-secondary" onclick="labVoiceReset()">重置视角</button></div></div><div class="voice-map-layout"><div class="voice-space-shell"><svg id="voiceSpace" class="voice-scatter" viewBox="0 0 820 520" role="group" aria-label="声学向量空间，拖动旋转，点选音色查看和试听" onpointerdown="labVoiceRotateStart(event)"><rect class="voice-space-bg" width="820" height="520" rx="12"/><g id="voiceSpaceContent">${labVoiceScene()}</g></svg><span class="voice-space-mark">PCA · 3D</span></div><div class="voice-legend">${clusters.map(c=>`<button data-cluster="${c}" aria-pressed="${labVoiceFilter===c}" onclick="labFocusVoice(${c})"><i style="background:${labClusterColors[c%4]}"></i><b>C${c+1}</b><span>${points.filter(p=>p.cluster===c).length} 音色</span></button>`).join('')}<button class="voice-show-all" onclick="labFocusVoice(null)">显示全部</button><p>点击簇可聚焦，其他音色仍可点选。连线指向簇中心；三维投影不代表音质或分类准确率。</p></div></div><div id="voiceSelection" class="voice-selection" aria-live="polite">点选一个音色，听听它的声音。</div>`;
 const selected=labVoiceData.points.findIndex(p=>p.file===labVoiceSelection);
 if(selected>=0)labSelectVoice(selected);else labVoiceSelection=null;
}
function labFocusVoice(cluster){
 labVoiceFilter=cluster;
 document.querySelectorAll('.voice-legend button[data-cluster]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.cluster)===cluster)));
 labUpdateVoiceSpace();
}
function labUpdateVoiceSpace(){const content=document.getElementById('voiceSpaceContent');if(content)content.innerHTML=labVoiceScene();}
function labVoiceReset(){labVoiceRotation={yaw:-34,pitch:18};labUpdateVoiceSpace();}
function labVoiceRotateStart(event){
 if(event.target.closest?.('.voice-point'))return;
 event.preventDefault();labVoiceDrag={x:event.clientX,y:event.clientY,yaw:labVoiceRotation.yaw,pitch:labVoiceRotation.pitch};
 window.addEventListener('pointermove',labVoiceRotateMove);window.addEventListener('pointerup',labVoiceRotateEnd,{once:true});
}
function labVoiceRotateMove(event){if(!labVoiceDrag)return;labVoiceRotation.yaw=labVoiceDrag.yaw+(event.clientX-labVoiceDrag.x)*.35;labVoiceRotation.pitch=Math.max(-55,Math.min(55,labVoiceDrag.pitch-(event.clientY-labVoiceDrag.y)*.28));labUpdateVoiceSpace();}
function labVoiceRotateEnd(){labVoiceDrag=null;window.removeEventListener('pointermove',labVoiceRotateMove);}
function labSelectVoice(index){
 const p=labVoiceData.points[index],cohort=labVoiceData.cohort_id;
 if(!p)return;labVoiceSelection=p.file;
 const src=cohort?`/api/voice/cohorts/${encodeURIComponent(cohort)}/audio/${encodeURIComponent(p.file)}`:`/api/tts/audio/${encodeURIComponent(p.file)}`;
 document.getElementById('voiceSelection').innerHTML=`<div><span>C${p.cluster+1} · 声学坐标</span><h2>${esc(p.name)}</h2><p>F0 ${Number(p.f0_mean).toFixed(1)} Hz · F1 ${Number(p.f1_mean).toFixed(1)} Hz · F2 ${Number(p.f2_mean).toFixed(1)} Hz</p></div>${p.audio_available?`<audio controls preload="none" src="${esc(src)}" aria-label="试听 ${esc(p.name)}"></audio>`:'<p>此音色的缓存音频暂不可用。</p>'}`;
 document.querySelectorAll('.voice-point').forEach(c=>{const selected=Number(c.dataset.index)===index;c.classList.toggle('selected',selected);c.setAttribute('aria-pressed',String(selected));});
}
function labNoisePlayer(id,label,preview){
 const src=`/api/channel/noise/preview/${encodeURIComponent(preview)}`;
 return `<audio controls preload="none" aria-label="试听${esc(label)}噪声" src="${src}"></audio>`;
}
let labOptions={},labHistory=[],labReviewRun=null,labWriting=false,labSelectedPair=null;
function labListenScene(id){
 const r=labData.job.result,pair=r?.blind_pairs?.find(p=>(r.rows||[]).some(row=>row.scene_id===id&&row.stem===p.stem));
 if(!pair)return;
 labSelectedPair={run:r.run_id,stem:pair.stem};labOpen('loop');
}
const labActionLabel=a=>({accept:'晋级候选版本',accept_conditional:'有条件晋级',iterate:'保留基准，继续迭代',no_solution:'保留基准，结束迭代',reject:'放弃本轮结果'}[a]||'查看判定');
function labCandidates(){const baseline=document.getElementById('labBaseline').value;document.getElementById('labCandidate').innerHTML=labOptions.versions.filter(v=>v.id!==baseline).map(v=>`<option value="${esc(v.id)}">${esc(v.label)}</option>`).join('');}
function labRowsTable(rows){return `<div class="lab-table-wrap"><table><thead><tr><th>场景 / 音色</th><th>基准 PQ</th><th>候选 PQ</th><th>ΔPQ</th></tr></thead><tbody>${rows.map(r=>`<tr data-scene="${esc(r.scene_id)}"><td><span class="lab-scene-tag">${esc(r.noise_label||r.scene_id)}</span> ${esc(r.voice_name||r.voice_id||r.stem)}</td><td>${labNum(r.baseline_pq)}</td><td>${labNum(r.candidate_pq)}</td><td>${typeof r.baseline_pq==='number'&&typeof r.candidate_pq==='number'?labSigned(r.candidate_pq-r.baseline_pq):'—'}</td></tr>`).join('')}</tbody></table></div>`;}
function labSceneSummary(rows){
 const groups=labScenes.map(([id,label])=>({id,label,rows:rows.filter(r=>r.scene_id===id)})).filter(g=>g.rows.length);
 const mean=(items,key)=>{const values=items.map(r=>r[key]).filter(Number.isFinite);return values.length?values.reduce((a,b)=>a+b,0)/values.length:null;};
 return `<div class="lab-table-wrap lab-scene-summary"><table><thead><tr><th>场景</th><th>有效配对 / 总样本</th><th>基准均值</th><th>候选均值</th><th>平均 ΔPQ</th><th>回退</th></tr></thead><tbody>${groups.map(g=>{const paired=g.rows.filter(r=>Number.isFinite(r.baseline_pq)&&Number.isFinite(r.candidate_pq)),baseline=mean(paired,'baseline_pq'),candidate=mean(paired,'candidate_pq');return `<tr data-scene="${esc(g.id)}"><td><span class="lab-scene-tag">${esc(g.label)}</span></td><td>${paired.length} / ${g.rows.length}${paired.length<g.rows.length?` · ${g.rows.length-paired.length} 条缺测`:''}</td><td>${labNum(baseline)}</td><td>${labNum(candidate)}</td><td>${baseline!==null&&candidate!==null?labSigned(candidate-baseline):'—'}</td><td>${paired.filter(r=>r.candidate_pq<r.baseline_pq).length} / ${paired.length}</td></tr>`;}).join('')}</tbody></table></div>`;
}
function labReviewEntries(result){
 const rowByStem=new Map((result?.rows||[]).map(row=>[row.stem,row]));
 return (result?.blind_pairs||[]).map(pair=>{const row=rowByStem.get(pair.stem)||{};const baseline=row.baseline_pq,candidate=row.candidate_pq;return {pair,row,sceneId:row.scene_id||'',search:[pair.noise_label,row.noise_label,row.scene_id,row.voice_name,row.voice_id,pair.stem].filter(Boolean).join(' ').toLowerCase(),delta:Number.isFinite(baseline)&&Number.isFinite(candidate)?candidate-baseline:null};});
}
function labRecommendedPairs(result){
 const entries=labReviewEntries(result),picked=[];
 const choose=group=>{
   if(!group.length)return;
   const finite=group.filter(item=>Number.isFinite(item.delta)).sort((a,b)=>a.delta-b.delta);
   const median=finite.length?finite[Math.floor((finite.length-1)/2)].delta:0;
   const typical=(finite.length?finite:group).reduce((best,item)=>!best||Math.abs((item.delta??median)-median)<Math.abs((best.delta??median)-median)?item:best,null);
   picked.push(typical);
   if(group.length<2)return;
   const regression=finite.find(item=>item!==typical&&item.delta<0);
   const second=regression||group.filter(item=>item!==typical).sort((a,b)=>Math.abs((b.delta??median)-median)-Math.abs((a.delta??median)-median))[0];
   if(second)picked.push(second);
 };
 labScenes.forEach(([id])=>choose(entries.filter(item=>item.sceneId===id)));
 choose(entries.filter(item=>!labScenes.some(([id])=>id===item.sceneId)));
 return picked.map(item=>item.pair);
}
function labPairLabel(pair,rows){const row=rows.find(item=>item.stem===pair.stem)||{};return `${pair.noise_label||row.noise_label||row.scene_id||'未知场景'} · ${row.voice_name||row.voice_id||pair.stem}`;}
function labReview(){
  const r=labData.job.result;labReviewRun=r?.run_id||null;
  if(!r||r.status!=='ok')return `<div class="lab-explain"><h2>当前没有待复核结果</h2><p>完成一次版本比较后，在这里盲听并确认。本地已确认结果保存在实验历史中。</p><div class="lab-actions"><button class="lab-primary" onclick="labOpen('loop','run')">配置下一轮 →</button><button class="lab-secondary" onclick="labOpen('history')">查看历史判定</button></div></div>`;
  const pairs=r.blind_pairs||[], rows=r.rows||[];
  const recommended=labRecommendedPairs(r),selected=pairs.find(p=>labSelectedPair?.run===r.run_id&&labSelectedPair.stem===p.stem);if(selected&&!recommended.some(p=>p.stem===selected.stem))recommended.unshift(selected);
  return `<div class="lab-review-context"><strong>${esc(r.baseline)} → ${esc(r.candidate)}</strong><span>待人工确认 · ${rows.length} 个样本</span></div><section class="lab-listening"><h2>先听差异</h2><p class="lab-listening-note">已从每个场景抽取 1–2 条代表样本。先听这 ${recommended.length} 条；需要定位具体音色时，再搜索完整样本。</p><label>建议试听<select id="labPairSelect" onchange="labPair()">${recommended.map(p=>`<option value="${esc(p.stem)}" ${selected?.stem===p.stem?'selected':''}>${esc(labPairLabel(p,rows))}</option>`).join('')}</select></label><div id="labPairAudio"></div><div class="lab-actions">${['A','B','tie'].map(p=>`<button class="lab-secondary lab-vote" onclick="labVote('${p}')" ${pairs.length?'':'disabled'}>${p==='tie'?'听感持平':p+' 更好'}</button>`).join('')}</div><p id="labVoteFeedback" role="status"></p><details class="lab-sample-search"><summary>查找其他样本 · ${pairs.length} 条</summary><label>输入场景、音色或样本 ID<input id="labPairSearch" oninput="labFilterPairs(this.value)" autocomplete="off"></label><div id="labPairSearchResults"><p>输入关键词后显示匹配结果。</p></div></details></section><section class="lab-explain"><h2>再看判定</h2><p>${esc(r.decision?.reason||'尚未生成建议')}</p><details><summary>工程 Gate · 展开依据</summary>${(r.judge?.gate_checks||[]).map(g=>`<p>${g.pass?'✓':'×'} ${esc(g.label)} · 实际 ${esc(g.actual)} / 阈值 ${esc(g.threshold)}</p>`).join('')}</details><div class="lab-actions"><button class="lab-primary" onclick="labApplyDialog()">${esc(labActionLabel(r.decision?.action))} →</button><button class="lab-secondary" onclick="labApplyDialog(true)">放弃本轮结果</button></div><p>确认后才写入正式历史；播放和听感记录不会自动晋级版本。</p></section>`;
}
function labFilterPairs(query){
 const host=document.getElementById('labPairSearchResults'),r=labData?.job?.result;if(!host||!r)return;const text=String(query||'').trim().toLowerCase();
 if(!text){host.innerHTML='<p>输入关键词后显示匹配结果。</p>';return;}
 const matches=labReviewEntries(r).filter(item=>item.search.includes(text)).slice(0,12);
 host.innerHTML=matches.length?`<div class="lab-search-results">${matches.map(item=>`<button class="lab-secondary" onclick="labChoosePair('${encodeURIComponent(item.pair.stem)}')">${esc(labPairLabel(item.pair,r.rows||[]))}</button>`).join('')}</div><p>${matches.length===12?'仅显示前 12 条，请继续缩小关键词。':`找到 ${matches.length} 条。`}</p>`:'<p>没有匹配样本。</p>';
}
function labChoosePair(encodedStem){const r=labData?.job?.result;if(!r)return;labSelectedPair={run:r.run_id,stem:decodeURIComponent(encodedStem)};labPanel();}
function labPair(){
 const host=document.getElementById('labPairAudio');if(!host)return;const stem=document.getElementById('labPairSelect').value,r=labData.job.result;
 document.querySelectorAll('audio').forEach(a=>a.pause());
 if(!r||r.run_id!==labReviewRun){host.innerHTML='<p>本轮状态已变化，请重新进入听审页。</p>';return;}
 if(!stem){host.innerHTML='<p>此结果没有可用的盲听音频。</p>';return;}
 labSelectedPair={run:r.run_id,stem};
 const row=(r.rows||[]).find(x=>x.stem===stem)||{};host.dataset.scene=row.scene_id||'';
 host.innerHTML=`<div class="lab-audio-pair">${['A','B'].map(side=>`<div><h3>音频 ${side}</h3><audio controls preload="none" aria-label="盲听音频 ${side}" src="/api/loop/blind/audio/${encodeURIComponent(r.run_id)}/${encodeURIComponent(stem)}/${side}"></audio></div>`).join('')}</div>`;
 document.getElementById('labVoteFeedback').textContent='A/B 已盲化，不显示版本身份。';
}
async function labVote(pick){
 if(labWriting)return;labWriting=true;
 const message=document.getElementById('labVoteFeedback'),stem=document.getElementById('labPairSelect').value,run=labReviewRun;
 const stillSelected=()=>document.getElementById('labVoteFeedback')===message&&labReviewRun===run&&document.getElementById('labPairSelect')?.value===stem;
 message.textContent='正在记录听感…';document.querySelectorAll('.lab-vote').forEach(b=>b.disabled=true);
 try{await labPost('/api/loop/listen',{run_id:run,stem,pick});if(stillSelected())message.textContent=`已记录：${pick==='tie'?'听感持平':pick+' 更好'}`;}
 catch(e){if(stillSelected())message.textContent=e.message;}
 finally{labWriting=false;document.querySelectorAll('.lab-vote').forEach(b=>b.disabled=!document.getElementById('labPairSelect')?.value);}
}
function labDialog(title,body,action){
 document.getElementById('labDialog')?.remove();const d=document.createElement('dialog');d.id='labDialog';d.setAttribute('aria-labelledby','labDialogTitle');d.innerHTML=`<h2 id="labDialogTitle">${esc(title)}</h2>${body}<p id="labDialogError" role="alert"></p><div class="lab-actions"><button class="lab-secondary" id="labDialogCancel">取消</button><button class="lab-primary" id="labDialogConfirm">确认</button></div>`;document.body.append(d);d.querySelector('#labDialogCancel').onclick=()=>d.close();d.querySelector('#labDialogConfirm').onclick=async()=>{const b=d.querySelector('#labDialogConfirm');b.disabled=true;try{await action();d.close();}catch(e){d.querySelector('#labDialogError').textContent=e.message;}finally{b.disabled=false;}};d.showModal();
}
function labApplyDialog(reject=false){
 const result=labData.job.result;if(!result||result.run_id!==labReviewRun)return;
 const action=reject?'reject':result.decision?.action;
 labDialog(labActionLabel(action),`<p>${reject?'放弃当前临时结果，不改变基准。':'确认将采用本轮建议并写入正式实验历史。'}</p><p>${esc(result.baseline)} → ${esc(result.candidate)}</p>`,async()=>{const fresh=await labGet('/api/loop/job');if(fresh.result?.run_id!==result.run_id)throw new Error('结果已变化，请关闭并重新复核。');await labPost('/api/loop/apply',{decision:reject?{action:'reject'}:result.decision});++labPollEpoch;await labRefresh();labOpen('history');});
}
function labNewDialog(){if(labSubmitting)return;labDialog('开始一个新实验',`<p>当前实验的已确认历史会归档，未确认结果会清空。TTS 音频与计算缓存保留。</p>`,async()=>{await labPost('/api/loop/new',{});++labPollEpoch;labSignature='';await labRefresh();labOpen('loop','run');});}
async function labCancel(){try{await labPost('/api/loop/cancel',{});await labRefresh();}catch(e){document.getElementById('labRunFeedback').textContent=e.message;}}
async function labReport(){
  labDialog('实验报告','<p>先看结论和轮次摘要；逐样本数据下载 Excel 后筛选。</p><div id="labReportContent" role="status">正在读取报告…</div>',async()=>{});
 const dialog=document.getElementById('labDialog'),content=document.getElementById('labReportContent');
 dialog.classList.add('lab-report-dialog');
 document.getElementById('labDialogCancel').hidden=true;
 document.getElementById('labDialogConfirm').textContent='关闭';
  try{const d=await labGet('/api/loop/report'),s=d.summary||{},rounds=[...(d.rounds||[])].sort((a,b)=>String(b.time||'').localeCompare(String(a.time||''))),statusLabel=({running:'进行中',review:'待复核',done:'已完成',idle:'待开始'}[s.status]||s.status||'—');content.innerHTML=`<div class="lab-report-summary"><article><span>当前比较</span><strong>${esc(s.baseline||'—')} → ${esc(s.candidate||'—')}</strong></article><article><span>已确认轮次</span><strong>${rounds.length}</strong></article><article><span>工作区状态</span><strong>${esc(statusLabel)}</strong></article></div>${s.recommendation?.version?`<section class="lab-report-callout"><span>跨版本工程推荐</span><h3>${esc(s.recommendation.version)}</h3><p>${esc(s.recommendation.reason||'')}</p></section>`:''}<div class="lab-table-wrap lab-report-rounds"><table><thead><tr><th>轮次</th><th>版本</th><th>常规 ΔPQ</th><th>工程判定</th><th>时间</th></tr></thead><tbody>${rounds.map(r=>`<tr><td>第 ${esc(r.round)} 轮</td><td>${esc(r.baseline)} → ${esc(r.candidate)}</td><td>${labSigned(r.judge?.regular_delta)}</td><td>${esc(r.judge?.verdict||labActionLabel(r.decision?.action))}</td><td>${esc(r.time||'—')}</td></tr>`).join('')||'<tr><td colspan="5">暂无已确认实验</td></tr>'}</tbody></table></div><p class="lab-listening-note">网页保留结论层级，完整逐样本证据和判定说明放在 Excel；Markdown 原文仍可下载归档。</p><div class="lab-actions"><a class="lab-primary" href="/api/loop/report.xlsx">下载 Excel 明细</a><a class="lab-secondary" href="/api/loop/report.md">下载 Markdown 原文</a></div>`;}
 catch(e){content.innerHTML=`<p role="alert">报告读取失败：${esc(e.message)}</p><button class="lab-secondary" onclick="labReport()">重试</button>`;}
}
document.addEventListener('play',event=>{if(event.target.tagName==='AUDIO')document.querySelectorAll('audio').forEach(a=>{if(a!==event.target)a.pause();});},true);
