/* Version evidence: server scores remain the source of truth. */
const insightVersions = ['v1', 'v2', 'v3', 'v4'];
let insightSummary = null;
let insightMode = 'pq';
let insightScene = null;
const insightSceneTones = {
  NPARK: 'park',
  OOFFICE: 'office',
  PCAFETER: 'cafe',
  PRESTO: 'canteen',
  STRAFFIC: 'traffic',
  TMETRO: 'metro',
};
const insightNumber = value => value != null && Number.isFinite(Number(value)) ? Number(value) : null;
const insightFmt = value => insightNumber(value) == null ? '未测' : Number(value).toFixed(3);
const insightSigned = value => insightNumber(value) == null ? '未测' : `${value > 0 ? '+' : ''}${Number(value).toFixed(3)}`;
const insightTone = scene => insightSceneTones[scene?.scene_id] || 'default';

function insightScores(scene, summary) {
  const row = (summary.scenes || []).find(item => item.noise_label === scene.noise_label && Number(item.snr_db) === Number(scene.snr_db));
  return insightVersions.map(version => insightNumber(row?.scores?.[version]));
}

function insightPlot(values, {label, min, max, winner, delta = false, large = false, compact = false} = {}) {
  const width = large ? 580 : 380, height = large ? 214 : 184;
  const left = compact ? 14 : 42, right = width - 24, top = 30, bottom = height - 34;
  const finite = values.filter(value => value != null);
  if (!finite.length) return '<div class="insight-empty">尚无可比较的评分</div>';
  if (min == null) min = Math.floor((Math.min(...finite) - .15) * 2) / 2;
  if (max == null) max = Math.ceil((Math.max(...finite) + .15) * 2) / 2;
  if (max <= min) max = min + 1;
  const x = index => left + index * (right - left) / 3;
  const y = value => bottom - (value - min) / (max - min) * (bottom - top);
  const ticks = [min, (min + max) / 2, max];
  const grid = ticks.map(tick => `<g class="plot-grid"><line x1="${left}" x2="${right}" y1="${y(tick)}" y2="${y(tick)}"/>${compact ? '' : `<text x="${left-10}" y="${y(tick)+4}" text-anchor="end">${delta && tick > 0 ? '+' : ''}${tick.toFixed(1)}</text>`}</g>`).join('');
  // Keep missing measurements as gaps, at their original version positions.
  let pen = false;
  const path = values.map((value, index) => {
    if (value == null) { pen = false; return ''; }
    const command = `${pen ? 'L' : 'M'} ${x(index)} ${y(value)}`; pen = true; return command;
  }).join(' ');
  const area = compact && values.every(value=>value!=null) ? `M ${x(0)} ${bottom} L ${values.map((value,index)=>`${x(index)} ${y(value)}`).join(' L ')} L ${x(values.length-1)} ${bottom} Z` : '';
  const labels = values.map((value, index) => `<text class="plot-version" x="${x(index)}" y="${height-9}" text-anchor="middle">${insightVersions[index].toUpperCase()}</text>${value == null ? '' : `<g class="plot-point ${insightVersions[index]===winner?'is-winner':''}"><circle cx="${x(index)}" cy="${y(value)}" r="${insightVersions[index]===winner?5:3.5}"/>${!compact || insightVersions[index]===winner ? `<text x="${x(index)}" y="${y(value)-12}" text-anchor="middle">${compact ? insightVersions[index].toUpperCase()+' · ' : ''}${delta ? insightSigned(value) : insightFmt(value)}</text>` : ''}<title>${insightVersions[index].toUpperCase()} · ${delta?'ΔPQ':'PQ'} ${insightFmt(value)}</title></g>`}`).join('');
  return `<svg class="insight-plot" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(label)}：${values.map((v,i)=>`${insightVersions[i]} ${insightFmt(v)}`).join('，')}">${grid}${area?`<path class="plot-area" d="${area}"/>`:''}<path class="plot-line" d="${path}"/>${labels}</svg>`;
}

function insightWeighting(summary) {
  const scenes = summary.scene_cluster_charts || [];
  const clusters = summary.cluster_weights || [];
  return `<details class="insight-weighting"><summary>推荐如何算出来？<span>场景权重 × 簇自然占比 <b>⌄</b></span></summary><div class="weighting-body"><div><h4>场景的重要程度</h4>${scenes.map(scene=>`<div class="weight-row"><span>${esc(scene.noise_label)}</span><div class="weight-track"><i style="width:${Number(scene.effective_weight)*100}%"></i></div><b>${(Number(scene.effective_weight)*100).toFixed(0)}%</b></div>`).join('')}</div><div><h4>每个音色等权，簇按人数占比</h4>${clusters.map(cluster=>`<div class="weight-row"><span>${esc(cluster.cluster)} · ${cluster.voice_count} 音色</span><div class="weight-track cluster"><i style="width:${Number(cluster.weight)*100}%"></i></div><b>${(Number(cluster.weight)*100).toFixed(1)}%</b></div>`).join('')}<p>综合 PQ = Σ 场景权重 × Σ 簇占比 × 该簇场景 PQ。这里只加权 PQ，不混入 PC、CE 或 CU。</p></div></div></details>`;
}

function insightBoard(summary) {
  insightSummary = summary;
  const weighted = summary.weighted_versions || [];
  const winner = summary.recommendation?.version;
  const ranked = weighted.filter(item=>insightNumber(item.score)!=null).slice().sort((a,b)=>b.score-a.score);
  const first = ranked.find(item=>item.version===winner);
  const runner = ranked.find(item=>item.version!==winner);
  const source = loopStatusCache?.benchmark_run;
  return `<div class="insight-source"><span><i></i> ${source?'已保存的固定基准结果':'当前可比评分'}${source?.completed_at?` · ${esc(source.completed_at)}`:''}</span><span>${summary.shared_samples} 个相同条件 · PQ 越高越好</span></div>
    <div class="insight-hero"><div class="insight-recommendation"><span class="insight-eyebrow">固定尺子 · 不是本轮结论</span><h3>${esc((winner||'—').toUpperCase())}<span>在 V1–V4 赛马上领先</span></h3><div class="insight-score">${insightFmt(first?.score)} <small>PQ</small></div><p>${runner?`比次优 ${esc(runner.version.toUpperCase())} 高 <b>${insightSigned(first.score-runner.score)}</b> PQ。`:''} 这不是本轮 Candidate 是否晋级的判定。${esc(summary.recommendation?.risk||'请结合场景差异与工程 Gate 复核。')}</p><button class="btn-primary" type="button" onclick="reviewInsightWinner()">${loopLastResult?'返回本轮结论':'用这把尺子去比较'} <span>→</span></button><small>加权领先只说明尺子上谁分高；本轮晋级只看人工复核。</small></div>
    <div class="insight-composite"><div class="insight-chart-heading"><b>综合加权趋势</b><span>相同条件 · V1 → V4</span></div>${insightPlot(insightVersions.map(v=>insightNumber(weighted.find(item=>item.version===v)?.score)),{label:'四版本综合加权 PQ',winner,large:true})}<div class="insight-version-key">${weighted.map(item=>`<span class="${item.version===winner?'selected':''}"><i></i>${esc(item.version.toUpperCase())}<b>${insightFmt(item.score)}</b></span>`).join('')}</div></div></div>
    ${insightWeighting(summary)}
    <details class="scene-review" open><summary>六个场景的表现 <span>点击任一卡片查看声线簇</span></summary><div class="insight-scenes-head"><div><h3>每个场景，改善了吗？</h3></div><div class="insight-switch" role="group" aria-label="图表指标"><button type="button" aria-pressed="${insightMode==='pq'}" onclick="setInsightMode('pq')">绝对 PQ</button><button type="button" aria-pressed="${insightMode==='delta'}" onclick="setInsightMode('delta')">相对 ${esc((summary.reference_version||'v1').toUpperCase())}</button></div></div><div id="insightScenes"></div><div id="insightDetail" hidden></div></details>`;
}

function reviewInsightWinner() {
  if (loopLastResult) { selectLoopPage('conclusion'); return; }
  const winner = insightSummary?.recommendation?.version;
  const select = document.getElementById('loopCandidate');
  if (winner && winner !== loopStatusCache.baseline && [...select.options].some(option=>option.value===winner)) {
    select.value = winner; onLoopCandidateChange();
  }
  selectLoopPage('run');
  select.focus({preventScroll:true});
}

function setInsightMode(mode) {
  insightMode = mode;
  document.querySelectorAll('.insight-switch button').forEach((button,index)=>button.setAttribute('aria-pressed',String(index===(mode==='pq'?0:1))));
  renderInsightScenes();
  if(insightScene!=null) openInsightScene(insightScene);
}

function renderInsightScenes() {
  const summary = insightSummary;
  const host = document.getElementById('insightScenes');
  if (!summary || !host) return;
  const scenes = summary.scene_cluster_charts || [];
  const reference = insightVersions.indexOf(summary.reference_version || 'v1');
  const winner = summary.recommendation?.version;
  const lists = scenes.map(scene=>{
    const values = insightScores(scene,summary);
    return insightMode==='pq'?values:values.map(value=>value==null||values[reference]==null?null:value-values[reference]);
  });
  const all = lists.flat().filter(value=>value!=null);
  const min = all.length ? Math.floor((Math.min(...all)-.15)*2)/2 : 0;
  const max = all.length ? Math.ceil((Math.max(...all)+.15)*2)/2 : 1;
  host.innerHTML = `<div class="insight-scene-grid">${scenes.map((scene,index)=>{
    const scores = insightScores(scene,summary);
    const wi = insightVersions.indexOf(winner);
    const improvement = scores[wi]==null||scores[reference]==null?null:scores[wi]-scores[reference];
    const best = scores.reduce((a,value,i)=>value!=null&&(a<0||value>scores[a])?i:a,-1);
    const sceneWinner = best < 0 ? winner : insightVersions[best];
    return `<button class="insight-scene" data-tone="${insightTone(scene)}" data-scene="${esc(scene.scene_id)}" type="button" id="insightScene${index}" aria-expanded="${insightScene===index}" aria-controls="insightDetail" onclick="openInsightScene(${index})"><div class="insight-scene-title"><h4><i class="scene-tone-dot" aria-hidden="true"></i>${esc(scene.noise_label)}</h4><span class="scene-snr">SNR ${scene.snr_db} dB</span></div><div class="scene-noise-meter" aria-label="场景噪声强度"><i></i></div>${insightPlot(lists[index],{label:scene.noise_label,min,max,winner:sceneWinner,delta:insightMode==='delta',compact:true})}<div class="insight-scene-foot"><span class="scene-result"><small>综合推荐 ${esc((winner||'—').toUpperCase())} 较 ${esc((summary.reference_version||'v1').toUpperCase())}</small><b class="${improvement<0?'negative':''}">${insightSigned(improvement)}</b></span><span class="scene-drill">四簇 <b>↗</b></span></div></button>`;
  }).join('')}</div><p class="insight-axis-note">六张图使用同一纵轴（${min.toFixed(1)}–${max.toFixed(1)}，非零起点）；横轴为版本顺序。曲线标注场景最佳，底部为综合推荐版本的改善；完整数值见原始证据。</p>`;
}

function openInsightScene(index) {
  const scene = insightSummary.scene_cluster_charts[index];
  if (!scene) return;
  insightScene = index;
  const host = document.getElementById('insightDetail');
  const ref = insightSummary.reference_version || 'v1';
  const tone = insightTone(scene);
  host.hidden = false;
  host.className = `insight-detail insight-detail--${tone}`;
  host.dataset.scene = scene.scene_id;
  host.innerHTML = `<div class="insight-detail-head"><div><span class="insight-eyebrow"><i class="scene-tone-dot" aria-hidden="true"></i>场景证据</span><h3>${esc(scene.noise_label)}</h3><p class="insight-detail-subtitle">${scene.snr_db} dB · ${bestSceneCopy(scene)}</p></div><button type="button" class="btn-ghost" onclick="closeInsightScene()" aria-label="关闭场景详情">关闭 ×</button></div><div class="insight-detail-table"><table><caption>${insightMode==='delta'?'各簇相对参考版本 ΔPQ':'各簇绝对 PQ'} · 缺失测量保留为空</caption><thead><tr><th>声线簇 / 自然占比</th>${insightVersions.map(v=>`<th>${v.toUpperCase()}${v===ref?' · 参考':''}</th>`).join('')}</tr></thead><tbody>${scene.clusters.map(cluster=>`<tr><th>${esc(cluster.cluster)} <small>${cluster.voice_count} 音色</small></th>${insightVersions.map(version=>`<td class="${version===insightSummary.recommendation?.version?'recommended':''}">${insightClusterValue(cluster,version,ref)}</td>`).join('')}</tr>`).join('')}</tbody></table></div><div class="insight-detail-foot"><p>簇内每个音色等权；场景总分按簇的音色数量加权。</p><button class="text-action" type="button" onclick="openInsightEvidence(${index})">查看原始评分与音频 →</button></div>`;
  document.querySelectorAll('.insight-scene').forEach((button,i)=>button.setAttribute('aria-expanded',String(i===index)));
  host.scrollIntoView({behavior:'smooth',block:'center'});
  host.querySelector('button').focus({preventScroll:true});
}

function closeInsightScene() {
  document.getElementById('insightDetail').hidden = true;
  const button = document.getElementById(`insightScene${insightScene}`);
  button?.setAttribute('aria-expanded','false'); button?.focus();
  insightScene = null;
}

function openInsightEvidence(index) {
  const scene = insightSummary.scene_cluster_charts[index];
  const select = document.getElementById('versionRawScene');
  select.value = scene.scene_id; renderVersionRawTable();
  select.closest('details').open = true;
  select.scrollIntoView({behavior:'smooth',block:'center'}); select.focus({preventScroll:true});
}

document.addEventListener('keydown',event=>{
  if(event.key==='Escape' && insightScene!=null) closeInsightScene();
});

function renderLoopObserver(status={}, job={}, disconnected=false) {
  const host = document.getElementById('loopObserver');
  if (!host) return;
  host.hidden = !status.baseline;
  if (host.hidden) return;
  const events = job.events || [];
  const stages = [['prepare','固定输入'],['dut','降噪处理'],['evaluate','PQ 评测'],['decision','归因与 Gate'],['review','人工复核']];
  const current = job.stage || (job.state==='done'?'review':'prepare');
  const active = stages.findIndex(([key])=>key===current);
  const labels = {idle:'尚未启动',running:'后台运行中',done:'结果已生成 · 待复核',error:'本轮失败',cancelled:'本轮已取消'};
  const rounds = status.rounds || [];
  const archive = status.history_archive || {};
  const visibleNumbers = new Set(archive.visible_rounds || []);
  const visibleRounds = visibleNumbers.size ? rounds.filter(round=>visibleNumbers.has(round.round)) : rounds;
  const started = job.started_at ? new Date(job.started_at).getTime() : null;
  const end = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
  const elapsed = started && Number.isFinite(started) ? Math.max(0,Math.floor((end-started)/1000)) : null;
  const time = elapsed==null?'':` · 耗时 ${Math.floor(elapsed/60)}分${elapsed%60}秒`;
  const updated = job.updated_at ? new Date(job.updated_at).toLocaleTimeString('zh-CN',{hour12:false}) : null;
  host.innerHTML = `<div class="observer-head"><b>${disconnected?'连接中断 · 正在重新获取状态':labels[job.state]||'尚未启动'}</b><small>${esc(status.baseline.toUpperCase())} → ${esc((status.candidate||'待选版本').toUpperCase())}${time}</small></div><div class="observer-stages">${stages.map(([key,label],index)=>{
    const seen = events.find(event=>event.stage===key);
    const state = job.state==='idle'?'':index===active?'active':seen?'done':'';
    const caption = job.state==='idle'?'等待':index===active?(job.state==='error'?'失败':job.state==='cancelled'?'已停止':job.state==='done'?'等待确认':'进行中'):seen?'已执行':'等待';
    return `<div class="observer-stage ${state}"><b>${label}</b><span>${caption}</span></div>`;
  }).join('')}</div><div class="observer-meta" role="status">${disconnected?'暂时无法确认后台进度，请勿重复启动。':esc(job.message||'固定基准评分可先查看；启动后这里显示本轮真实阶段。')}${updated?` · 后台最后更新 ${updated}`:''}${job.total?` · 当前阶段 ${job.done||0}/${job.total}`:''}${job.run_id?`<br>Run ${esc(job.run_id)}`:''}</div><div class="observer-actions">${job.state==='running'?`<button class="text-action" type="button" onclick="cancelLoopRun()" ${job.cancel_requested?'disabled':''}>${job.cancel_requested?'正在等待安全停止…':'取消本轮'}</button>`:''}${job.state==='error'||job.state==='cancelled'?'<button class="text-action" type="button" onclick="runLoop()">重新运行 →</button>':''}${job.state==='done'?'<button class="text-action" type="button" onclick="selectLoopPage(\'conclusion\')">查看本轮结果与复核 →</button>':''}<button type="button" class="text-action" onclick="showView('loop','loopLogCard')">查看当前月份 ${visibleRounds.length} 轮历史 →</button></div>${archive.archived_count?`<div class="history-archive-note">已将超过 ${archive.archive_after_days||7} 天的 ${archive.archived_count} 轮记录归档到本地，仍可随时找回。</div>`:''}${visibleRounds.length?`<details class="iteration-history"><summary>最近已确认轮次 · 展开查看版本调整与结果</summary><p class="observer-meta">${esc(archive.current_period_label||'当前月份')} · 历史测试条件可能不同，请展开证据核对。</p><div class="iteration-strip">${visibleRounds.slice(-3).map(round=>`<div class="iteration-step"><span>第 ${round.round} 轮 · ${esc(round.time||'时间未记录')}</span><b>${esc(round.baseline)} → ${esc(round.candidate)} · ${esc({accept:'晋级',accept_conditional:'条件晋级',iterate:'回滚',no_solution:'无解'}[round.decision?.action]||'已确认')}</b><p>${esc(round.decision?.hypothesis||round.judge?.verdict||'查看本轮证据')}${round.judge&&!round.judge.policy_version?'（旧判据）':''}</p></div>`).join('')}</div></details>`:''}`;
  if (events.length) {
    document.getElementById('loopTrace').innerHTML=events.map(event=>`<div class="trace-entry" data-state="${event.stage===current&&job.state==='running'?'running':'done'}"><time>${new Date(event.time).toLocaleTimeString('zh-CN',{hour12:false})}</time><div><b>${esc(event.message)}</b><p>${event.total?`${event.done}/${event.total}`:''}</p></div></div>`).join('');
  }
}

async function cancelLoopRun() {
  try {
    const response = await fetch('/api/loop/cancel',{method:'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.message||'取消失败');
    await pollLoopJob();
  } catch (error) {
    document.querySelector('#loopObserver .observer-meta').textContent=`取消请求失败：${error.message}。后台状态仍在刷新。`;
  }
}

function bestSceneCopy(scene) {
  const scores = insightScores(scene, insightSummary);
  const best = scores.reduce((index, value, current) => value != null && (index < 0 || value > scores[index]) ? current : index, -1);
  return best < 0 ? '暂无完整测量' : `${insightVersions[best].toUpperCase()} 场景最优 · 展开查看 C1–C4`;
}

function jumpAnalysis(id) {
  selectLoopPage(loopPageForTarget(id));
}

function insightClusterValue(cluster, version, reference) {
  const value=insightNumber(cluster.values.find(item=>item.version===version)?.pq);
  const base=insightNumber(cluster.values.find(item=>item.version===reference)?.pq);
  return insightMode==='delta' ? insightSigned(value==null||base==null?null:value-base) : insightFmt(value);
}
