// 開發專用：設定後，Camera 不開實體相機，capture() 直接回這張預設圖（測 UI 流程用）。
let _e2eSample = null;
export function setE2ESample(dataUrl) { _e2eSample = dataUrl; }

export class Camera {
  constructor(videoEl, canvasEl) {
    this.video = videoEl;
    this.canvas = canvasEl;
    this.stream = null;
  }

  get isRecording() { return this.stream !== null; }

  async start() {
    if (this.stream) return;
    if (_e2eSample) { this.stream = 'e2e'; return; } // 開發：跳過相機
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } }, audio: false,
    });
    this.video.srcObject = this.stream;
    this.video.muted = true;
    await this.video.play();
  }

  capture() {
    if (!this.stream) return null;
    if (this.stream === 'e2e') return _e2eSample; // 開發：回預設收據圖
    const ctx = this.canvas.getContext('2d');
    this.canvas.width = this.video.videoWidth || 640;
    this.canvas.height = this.video.videoHeight || 480;
    ctx.drawImage(this.video, 0, 0);
    return this.canvas.toDataURL('image/jpeg', 0.85); // 單張、僅記憶體
  }

  stop() {
    if (this.stream) {
      if (this.stream !== 'e2e') this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
  }
}
