/* Navigation follows the current task; measurements remain server-owned. */
let loopPage = null;
let loopPageState = null;
const loopScroll = {};
const loopPages = ['conclusion', 'evidence', 'listen', 'compare', 'run', 'history'];

function sceneIdOf(idOrLabel = '') {
  const value = String(idOrLabel).toUpperCase();
  if (/NPARK|安静|公园/.test(value)) return 'NPARK';
  if (/OOFFICE|办公室/.test(value)) return 'OOFFICE';
  if (/PCAFETER|咖啡/.test(value)) return 'PCAFETER';
  if (/PRESTO|食堂/.test(value)) return 'PRESTO';
  if (/STRAFFIC|路口|交通/.test(value)) return 'STRAFFIC';
  if (/TMETRO|地铁|高噪/.test(value)) return 'TMETRO';
  return '';
}

function sceneBadge(idOrLabel, label) {
  const id = sceneIdOf(idOrLabel || label);
  return `<span class="scene-badge"${id ? ` data-scene="${id}"` : ''}>${esc(label || idOrLabel || '未知场景')}</span>`;
}

function selectLoopPage(page, focus = true) {
  if (!loopPages.includes(page)) page = 'conclusion';
  if (loopPage) loopScroll[loopPage] = window.scrollY;
  loopPage = page;
  if (focus && location.hash !== `#${page}`) history.pushState(null, '', `${location.pathname}${location.search}#${page}`);
  const view = document.getElementById('view-loop');
  view.dataset.page = page;
  document.querySelectorAll('[data-loop-pages]').forEach(el => {
    el.classList.toggle('page-excluded', !el.dataset.loopPages.split(' ').includes(page));
  });
  document.querySelectorAll('[data-loop-tab]').forEach(button => {
    const selected = button.dataset.loopTab === (['evidence', 'listen'].includes(page) ? 'conclusion' : page);
    button.setAttribute('aria-pressed', String(selected));
  });
  if (page === 'history') document.getElementById('loopLogCard').open = true;
  document.querySelectorAll('audio').forEach(audio => audio.pause());
  if (focus) {
    window.scrollTo({top:loopScroll[page] || 0, behavior:'instant'});
    document.getElementById('loopPageTitle').focus({preventScroll:true});
  }
  const names = {conclusion:'本轮结论', evidence:'场景证据', listen:'A/B 试听', compare:'固定尺子', run:'配置与运行', history:'实验历史'};
  document.getElementById('loopPageTitle').textContent = names[page];
}

function syncLoopPage(status = {}, job = {}) {
  const result = job.state === 'done' && job.result?.status === 'ok' ? job.result : null;
  const state = `${job.run_id || ''}:${job.state || 'idle'}`;
  if (!loopPage || state !== loopPageState) {
    const requested = location.hash.slice(1);
    selectLoopPage(loopPageState === null && loopPages.includes(requested) ? requested : result ? 'conclusion' : 'run', false);
    loopPageState = state;
  }
  const baseline = result?.baseline || status.baseline || '未建立';
  const candidate = result?.candidate || status.candidate || '待选择';
  document.getElementById('loopPageContext').textContent = `${baseline.toUpperCase()} → ${candidate.toUpperCase()} · ${{done:'待人工复核',running:'运行中',error:'运行失败',cancelled:'已取消',idle:'准备验证'}[job.state] || '准备验证'}`;
  const host = document.getElementById('loopConclusion');
  if (!result) {
    host.innerHTML = '<div class="conclusion-empty"><h2>本轮尚无待复核结论</h2><p>配置版本并完成运行后，在这里查看建议与依据。</p><button class="btn-primary" onclick="selectLoopPage(\'run\')">查看配置与运行 →</button></div>';
    return;
  }
  const judge = result.judge || {};
  const decision = result.decision || {};
  const title = {accept:`建议晋级 ${candidate.toUpperCase()}`,accept_conditional:`建议有条件晋级 ${candidate.toUpperCase()}`,iterate:`建议保留 ${baseline.toUpperCase()}`,no_solution:'本轮未找到可晋级版本'}[decision.action] || '本轮结果已生成';
  const summary = {accept:'新版本获得晋级建议。请复核场景表现后，决定是否替换当前基准。',accept_conditional:'新版本获得有条件晋级建议。请先核对回退场景与附加条件。',iterate:'本轮建议回滚，继续使用当前基准。查看场景证据，可以了解新版本的收益与回退。',no_solution:'当前候选未获得晋级建议。请查看证据与归因，再决定后续实验方向。'}[decision.action] || '结果已生成，请查看场景证据并完成复核。';
  host.innerHTML = `<div class="conclusion-lead"><span class="conclusion-label">本轮建议 · 尚未确认</span><h2>${esc(title)}</h2><p>${summary}</p></div><dl class="conclusion-metrics"><div><dt>常规平均 ΔPQ</dt><dd>${insightSigned(judge.regular_delta)}</dd></div><div><dt>常规回退样本</dt><dd>${judge.regular_retreat ?? '—'} <small>/ ${judge.n_regular ?? '—'}</small></dd></div><div><dt>比较版本</dt><dd class="metric-versions">${esc(baseline.toUpperCase())} → ${esc(candidate.toUpperCase())}</dd></div></dl><div class="conclusion-next"><button class="btn-primary" onclick="selectLoopPage('evidence')">查看场景证据 →</button><button class="btn-ghost" onclick="selectLoopPage('listen')">进入 A/B 试听</button><span>先复核，再确认是否写入历史。</span></div>`;
}

function loopPageForTarget(id) {
  return {loopObserver:'run',loopCommand:'run',loopVersionReview:'compare',loopPreviewSection:'conclusion',loopChartCard:'evidence',loopGoldenCard:'listen',loopLogCard:'history'}[id] || 'run';
}

document.addEventListener('play', event => {
  if (event.target.tagName !== 'AUDIO') return;
  document.querySelectorAll('audio').forEach(audio => { if (audio !== event.target) audio.pause(); });
}, true);

let loopReportFocus = null;
document.addEventListener('keydown', event => {
  const sheet = document.getElementById('loopReportSheet');
  if (!sheet?.classList.contains('open')) return;
  if (event.key === 'Escape') { event.preventDefault(); closeLoopReport(); }
  if (event.key === 'Tab') {
    const controls = [...sheet.querySelectorAll('button,summary,[tabindex="0"]')];
    const first = controls[0], last = controls[controls.length-1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});

function readableLoopReport(markdown) {
  // The report contains only headings, bullets, paragraphs and pipe tables.
  const lines = markdown.split('\n');
  let html = '', table = [], roundOpen = false;
  const inline = value => esc(value).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  const flush = () => {
    if (!table.length) return;
    html += '<div class="report-table"><table>' + table.filter(line => !/^\|[\s:|\-]+\|$/.test(line)).map((line,i) => '<tr>' + line.replace(/^\||\|$/g,'').split('|').map(cell => `<${i?'td':'th'}>${inline(cell.trim())}</${i?'td':'th'}>`).join('') + '</tr>').join('') + '</table></div>';
    table = [];
  };
  for (const line of lines) {
    if (line.startsWith('|')) { table.push(line); continue; }
    flush();
    if (/^## 第/.test(line)) {
      if (roundOpen) html += '</details>';
      html += `<details class="report-round"><summary>${inline(line.slice(3))}</summary>`;
      roundOpen = true;
    } else if (/^#{1,3} /.test(line)) {
      const level = Math.min(3, line.match(/^#+/)[0].length + 1);
      html += `<h${level}>${inline(line.replace(/^#+ /,''))}</h${level}>`;
    } else if (line.trim()) html += `<p>${inline(line.replace(/^- /,''))}</p>`;
  }
  flush();
  return html + (roundOpen ? '</details>' : '');
}
