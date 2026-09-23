/* 08 真机采集 · AudioWorklet
 *
 * 只做一件事：把音频线程里的原始 Float32 帧搬到主线程。
 * 刻意不做任何增益、滤波、降噪 —— 采集层的唯一职责是不污染信号。
 */
class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.stopped = false;
    this.port.onmessage = (event) => {
      if (event.data === 'stop') this.stopped = true;
    };
  }

  process(inputs) {
    const input = inputs[0];
    if (input && input.length > 0 && input[0]) {
      // slice(0) 复制一份，因为底层 buffer 会被复用
      this.port.postMessage(input[0].slice(0));
    }
    return !this.stopped;
  }
}

registerProcessor('capture-processor', CaptureProcessor);
