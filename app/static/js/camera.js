export class Camera {
  constructor(videoEl, canvasEl) {
    this.video = videoEl;
    this.canvas = canvasEl;
    this.stream = null;
  }

  get isRecording() { return this.stream !== null; }

  async start() {
    if (this.stream) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'user' }, audio: false,
    });
    this.video.srcObject = this.stream;
    this.video.muted = true;
    await this.video.play();
  }

  capture() {
    if (!this.stream) return null;
    const ctx = this.canvas.getContext('2d');
    this.canvas.width = this.video.videoWidth || 640;
    this.canvas.height = this.video.videoHeight || 480;
    ctx.drawImage(this.video, 0, 0);
    return this.canvas.toDataURL('image/jpeg', 0.85); // 單張、僅記憶體
  }

  stop() {
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
  }
}
