/* 08 真机采集 · 手机端页面逻辑
 *
 * 三条硬规则：
 * 1. 非安全上下文（http://<局域网IP>）直接拦下 —— 浏览器不会给麦克风权限，别让用户白试。
 * 2. AEC / NS / AGC 必须显式请求关闭，并且**回读实际值**；关不掉就如实告知会降级。
 * 3. 采集走 AudioWorklet 原始 Float32 → Int16，不用 MediaRecorder（避免 Opus 二次编码）。
 */

const $ = (id) => document.getElementById(id);

const state = {
  token: new URLSearchParams(location.search).get('t') || sessionStorage.getItem('sd_capture_token') || '',
  scripts: [],
  step: 0,
  rep: 0,
  sessionId: null,
  stream: null,
  ctx: null,
  node: null,
  source: null,
  seq: 0,
  pending: [],
  pendingSamples: 0,
  uploading: 0,
  uploaded: 0,
  gaps: 0,
  uploadChain: Promise.resolve(),
  uploadFailures: 0,
  ctxSampleRate: null,
  expectedSeq: 0,
  recording: false,
  manifest: {},
  startedAt: 0,
  timer: null,
};

function setStatus(text, kind = '') {
  const el = $('status');
  el.textContent = text;
  el.className = 'status ' + kind;
}

function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  if (state.token) headers['X-Capture-Token'] = state.token;
  return fetch(path, Object.assign({}, options, { headers }));
}

/* ------------------------------------------------------------------ *
 * 0. 安全上下文闸门
 * ------------------------------------------------------------------ */
function checkSecureContext() {
  const secure = window.isSecureContext === true;
  const hasMedia = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  if (secure && hasMedia) return true;
  $('gate').style.display = 'block';
  $('gate-detail').textContent = secure
    ? '当前浏览器没有暴露麦克风接口。'
    : `当前页面来源 ${location.origin} 不是安全上下文，浏览器会拒绝麦克风权限。`;
  $('app').style.display = 'none';
  return false;
}

/* ------------------------------------------------------------------ *
 * 1. 设备与约束回读
 * ------------------------------------------------------------------ */
async function openMic(deviceId) {
  const constraints = {
    audio: {
      deviceId: deviceId ? { exact: deviceId } : undefined,
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
      channelCount: 1,
      sampleRate: 48000,
    },
    video: false,
  };
  const stream = await navigator.mediaDevices.getUserMedia(constraints);
  const track = stream.getAudioTracks()[0];
  const settings = typeof track.getSettings === 'function' ? track.getSettings() : {};
  const applied = {
    aec_requested: false, ns_requested: false, agc_requested: false,
    aec_actual: settings.echoCancellation === undefined ? null : settings.echoCancellation,
    ns_actual: settings.noiseSuppression === undefined ? null : settings.noiseSuppression,
    agc_actual: settings.autoGainControl === undefined ? null : settings.autoGainControl,
    input_device_id: settings.deviceId || deviceId || '',
    input_label: track.label || '',
    sample_rate_reported: settings.sampleRate || null,
    channel_count_reported: settings.channelCount || null,
    ua: navigator.userAgent,
    secure_context: window.isSecureContext === true,
  };
  state.manifest = Object.assign(state.manifest, applied);
  renderConstraintWarning(applied);
  return stream;
}

function renderConstraintWarning(applied) {
  const forced = ['ns_actual', 'agc_actual', 'aec_actual']
    .filter((key) => applied[key] === true)
    .map((key) => key.split('_')[0].toUpperCase());
  const box = $('constraint-warning');
  if (forced.length === 0) {
    box.style.display = 'none';
    return;
  }
  const fatal = forced.includes('NS') || forced.includes('AGC');
  box.style.display = 'block';
  box.className = 'warn ' + (fatal ? 'fatal' : 'soft');
  box.innerHTML = fatal
    ? `<b>本机强制开启 ${forced.join(' / ')}</b><br>
       信号已经过系统处理，这次采集会被判为 <b>grade_c</b>，不进入任何比较。<br>
       请换用：外接耳机麦、或改用支持关闭处理链的浏览器（桌面 Chrome / Android Chrome）。`
    : `<b>无法关闭 ${forced.join(' / ')}</b><br>
       这次采集会被判为 <b>grade_b</b>，只能做探索性试听，不能进入版本晋级比较。`;
}

async function listDevices() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const inputs = devices.filter((d) => d.kind === 'audioinput');
  const select = $('device');
  select.innerHTML = '';
  inputs.forEach((device, index) => {
    const option = document.createElement('option');
    option.value = device.deviceId;
    option.textContent = device.label || `麦克风 ${index + 1}（未授权前无名称）`;
    select.appendChild(option);
  });
  if (inputs.length === 0) {
    const option = document.createElement('option');
    option.textContent = '未发现输入设备';
    option.value = '';
    select.appendChild(option);
  }
  return inputs;
}

function guessRoute(label) {
  const text = (label || '').toLowerCase();
  if (/(airpod|bt|bluetooth|wh-|wf-|freebuds|buds|蓝牙|headset|hands-free|hfp)/.test(text)) return 'bluetooth_hfp';
  if (/(usb|dac|audiointerface|scarlett)/.test(text)) return 'usb_mic';
  if (/(wired|line|headphone|耳机)/.test(text)) return 'wired_headset';
  if (/(built|内建|内置|phone|iphone|android|mic\b)/.test(text)) return 'phone_internal';
  return 'unknown';
}

/* ------------------------------------------------------------------ *
 * 2. 脚本引导
 * ------------------------------------------------------------------ */
function currentScript() {
  return state.scripts[state.step];
}

function renderGuide() {
  const script = currentScript();
  if (!script) {
    $('guide-text').textContent = '全部脚本已读完，可以封存。';
    $('guide-meta').textContent = '';
    $('btn-record').disabled = true;
    $('btn-finalize').disabled = false;
    return;
  }
  $('guide-text').textContent = script.text;
  $('guide-meta').textContent =
    `${script.kind} · 建议 ${script.expect_s}s · 第 ${state.rep + 1}/${script.reps} 次\n${script.note}`;
  $('btn-record').disabled = false;
  $('btn-finalize').disabled = true;
}

function advanceGuide() {
  const script = currentScript();
  if (!script) return;
  state.rep += 1;
  if (state.rep >= script.reps) {
    state.rep = 0;
    state.step += 1;
  }
  renderGuide();
}

/* ------------------------------------------------------------------ *
 * 3. 录制
 * ------------------------------------------------------------------ */
async function startRecording() {
  if (state.recording) return;
  const script = currentScript();
  if (!script) return;
  if (!state.sessionId) {
    setStatus('正在建立会话…');
    try {
      const res = await api('/api/capture/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          speaker_code: $('speaker').value.trim() || 'SPK-01',
          script_id: script.id,
          declared_route: $('route').value,
          client_manifest: state.manifest,
        }),
      });
      const data = await res.json();
      if (data.status !== 'ok') throw new Error(data.message || '建立会话失败');
      state.sessionId = data.session.session_id;
      $('session-id').textContent = state.sessionId;
    } catch (err) {
      setStatus('建立会话失败：' + err.message, 'bad');
      return;
    }
  }

  try {
    const deviceId = $('device').value || undefined;
    state.stream = await openMic(deviceId);
  } catch (err) {
    setStatus('打开麦克风失败：' + err.message, 'bad');
    return;
  }

  state.ctx = new AudioContext();
  // Worklet 吐出来的帧跑在 ctx.sampleRate 上，而 track.getSettings().sampleRate 只是约束申报值，
  // 两者在 iOS 上经常不一致。WAV 头、duration_s、hf_ratio_db 的 4kHz 高通都按这个值算，
  // 用错会让蓝牙窄带指纹直接失真 —— 所以以 ctx 实测速率为准，申报值只留作对照。
  state.ctxSampleRate = state.ctx.sampleRate;
  state.manifest.sample_rate_actual = state.ctx.sampleRate;
  await state.ctx.audioWorklet.addModule('/capture-worklet.js');
  state.source = state.ctx.createMediaStreamSource(state.stream);
  state.node = new AudioWorkletNode(state.ctx, 'capture-processor', {
    numberOfInputs: 1,
    numberOfOutputs: 0,
    channelCount: 1,
    channelCountMode: 'explicit',
  });
  state.node.port.onmessage = (event) => pushFrames(event.data);
  state.source.connect(state.node);

  state.recording = true;
  state.startedAt = performance.now();
  state.pending = [];
  state.pendingSamples = 0;
  $('btn-record').textContent = '停止';
  setStatus('录音中…' + script.text.slice(0, 12));

  state.timer = setInterval(() => {
    $('elapsed').textContent = ((performance.now() - state.startedAt) / 1000).toFixed(1) + 's';
  }, 100);
}

function pushFrames(frames) {
  let sum = 0;
  const pcm = new Int16Array(frames.length);
  for (let i = 0; i < frames.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, frames[i]));
    pcm[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    sum += clamped * clamped;
  }
  const rms = Math.sqrt(sum / frames.length);
  const dbfs = rms > 0 ? 20 * Math.log10(rms) : -100;
  $('meter').style.width = Math.max(0, Math.min(100, (dbfs + 60) / 60 * 100)).toFixed(0) + '%';
  state.pending.push(pcm);
  state.pendingSamples += pcm.length;
  if (state.pendingSamples >= (state.ctx ? state.ctx.sampleRate : 48000)) flushChunk();
}

function flushChunk() {
  if (state.pendingSamples === 0 || !state.sessionId) return state.uploadChain;
  const merged = new Int16Array(state.pendingSamples);
  let offset = 0;
  state.pending.forEach((pcm) => { merged.set(pcm, offset); offset += pcm.length; });
  state.pending = [];
  state.pendingSamples = 0;

  const seq = state.seq;
  state.seq += 1;
  state.uploading += 1;

  // 串行队列，不是并发。seq 是同步自增的、fetch 是异步的：一旦并发在途，
  // 移动网络下乱序抵达会让服务端把先到的大 seq 登记成断档、把后到的小 seq
  // 判成「重放」而静默丢弃 —— 真实音频没了，却不计入 dropped_frames。
  // 那正好是「丢帧必须如实记账」这条硬约束最怕的失败模式：账面干净，数据缺了。
  state.uploadChain = state.uploadChain.then(() => sendChunk(seq, merged));
  return state.uploadChain;
}

async function sendChunk(seq, merged) {
  try {
    const res = await api(
      `/api/capture/session/${state.sessionId}/chunk?seq=${seq}&frames=${merged.length}`,
      { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: merged.buffer }
    );
    const data = await res.json();
    if (data.status === 'ok' || data.status === 'replayed') {
      state.uploaded += 1;
      if (typeof data.gap_count === 'number') state.gaps = data.gap_count;
    } else {
      state.uploadFailures += 1;
      setStatus('上传被拒：' + (data.message || '未知原因'), 'bad');
    }
  } catch (err) {
    state.gaps += 1;
    state.uploadFailures += 1;
    setStatus('上传失败（计一次断档）：' + err.message, 'bad');
  } finally {
    state.uploading -= 1;
    $('chunk-stat').textContent = `已上传 ${state.uploaded} 段 / 断档 ${state.gaps}`;
  }
}

async function stopRecording() {
  if (!state.recording) return;
  state.recording = false;
  clearInterval(state.timer);
  if (state.node) {
    state.node.port.postMessage('stop');
    state.node.port.onmessage = null;
  }
  if (state.source) state.source.disconnect();
  if (state.ctx) await state.ctx.close();
  if (state.stream) state.stream.getTracks().forEach((track) => track.stop());
  flushChunk();
  await state.uploadChain;   // 等在途的全部落地：finalize 抢在前面会让尾段被服务端拒收且不入账
  state.ctx = null; state.node = null; state.source = null; state.stream = null;
  $('btn-record').textContent = '开始录制';
  setStatus('这一段已上传，换下一段或封存。');
  advanceGuide();
}

async function finalize() {
  if (state.recording) await stopRecording();
  if (!state.sessionId) { setStatus('还没有任何录音。', 'bad'); return; }
  await state.uploadChain;   // 未录制状态下也可能还有在途请求
  // 客户端侧失败的上传（尤其是最后一个 chunk）服务端看不到 seq 跳变，永远不会自己发现。
  state.manifest.client_upload_failures = state.uploadFailures;
  setStatus('正在封存并计算采集指标…');
  try {
    const res = await api(`/api/capture/session/${state.sessionId}/finalize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sample_rate: state.ctxSampleRate || state.manifest.sample_rate_reported || 48000,
        channel_count: 1,
        client_manifest: state.manifest,
      }),
    });
    const data = await res.json();
    if (data.status !== 'ok') throw new Error(data.message || '封存失败');
    renderResult(data.result);
  } catch (err) {
    setStatus('封存失败：' + err.message, 'bad');
  }
}

function renderResult(result) {
  const m = result.metrics;
  $('result').style.display = 'block';
  $('result-grade').textContent = result.capture_grade;
  $('result-grade').className = 'grade ' + result.capture_grade;
  $('result-reason').textContent = result.grade_reason;
  $('result-metrics').textContent =
    `时长 ${m.duration_s}s · RMS ${m.rms_dbfs} dBFS · 峰值 ${m.peak_dbfs} dBFS · ` +
    `静音占比 ${m.silence_ratio} · 高频占比 ${m.hf_ratio_db} dB · 削波 ${m.clip_ratio}`;
  $('player').src = `/api/capture/audio/${result.session_id}?t=${encodeURIComponent(state.token)}`;
  setStatus(result.usable_for_loop ? '封存完成，可用作生态效度校验语料。' : '封存完成，但未达到 grade_a。');
}

/* ------------------------------------------------------------------ *
 * 4. 启动
 * ------------------------------------------------------------------ */
async function boot() {
  if (state.token) sessionStorage.setItem('sd_capture_token', state.token);
  if (!checkSecureContext()) return;

  try {
    const res = await api('/api/capture/scripts');
    if (res.status === 401) {
      setStatus('配对令牌无效。请在桌面端重新生成二维码。', 'bad');
      $('app').style.display = 'none';
      return;
    }
    const data = await res.json();
    state.scripts = data.scripts || [];
  } catch (err) {
    setStatus('连不上本地工作台：' + err.message, 'bad');
    return;
  }

  renderGuide();
  try {
    await navigator.mediaDevices.getUserMedia({ audio: true });
    const inputs = await listDevices();
    const first = inputs[0];
    if (first) $('route').value = guessRoute(first.label);
  } catch (err) {
    setStatus('尚未获得麦克风权限，点“开始录制”时会再次申请。');
  }
  await listDevices();

  $('btn-refresh').onclick = async () => { await listDevices(); };
  $('device').onchange = async () => {
    if (state.stream) state.stream.getTracks().forEach((t) => t.stop());
    try {
      state.stream = await openMic($('device').value);
    } catch (err) {
      setStatus('切换设备失败：' + err.message, 'bad');
    }
  };
  $('btn-record').onclick = () => (state.recording ? stopRecording() : startRecording());
  $('btn-finalize').onclick = finalize;
  $('btn-next').onclick = () => { if (!state.recording) advanceGuide(); };
  setStatus('就绪。先确认输入路径，再按提示朗读。');
}

boot();
