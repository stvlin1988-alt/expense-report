import { Camera } from './camera.js';
import { captureUpload } from './expenses_api.js';

const root = () => document.getElementById('modal-root');

// 無腦拍單：快門 → [完成]/[下一張]；完成後逐張上傳、進度條；可離開。
export function showCaptureView(onDone) {
  root().innerHTML = `
    <div class="modal-backdrop"><div class="modal-box">
      <h2>拍單</h2>
      <video id="cap-video" autoplay playsinline muted></video>
      <canvas id="cap-canvas" style="display:none;"></canvas>
      <div id="cap-count" class="app-view-info">已拍 0 張</div>
      <div id="cap-actions">
        <button class="modal-btn" id="cap-shot" type="button">拍照</button>
      </div>
      <div id="cap-after" style="display:none;">
        <button class="modal-btn secondary" id="cap-next" type="button">下一張</button>
        <button class="modal-btn" id="cap-done" type="button">完成</button>
      </div>
      <div class="modal-msg" id="cap-msg"></div>
      <button class="modal-btn secondary" id="cap-back" type="button" style="margin-top:10px;">返回</button>
    </div></div>`;

  const cam = new Camera(document.getElementById('cap-video'), document.getElementById('cap-canvas'));
  const shots = [];
  const msg = document.getElementById('cap-msg');
  const count = document.getElementById('cap-count');
  const after = document.getElementById('cap-after');
  const shotBtn = document.getElementById('cap-shot');

  cam.start().catch(() => { msg.textContent = '無法開啟鏡頭'; });

  function takeShot() {
    if (!cam.isRecording) return;
    shots.push(cam.capture());           // base64 記憶體，不落地
    count.textContent = `已拍 ${shots.length} 張`;
    shotBtn.style.display = 'none';
    after.style.display = 'block';
  }
  shotBtn.addEventListener('click', takeShot);
  document.getElementById('cap-next').addEventListener('click', () => {
    after.style.display = 'none';
    shotBtn.style.display = 'block';
  });
  document.getElementById('cap-back').addEventListener('click', () => { cam.stop(); onDone(); });

  document.getElementById('cap-done').addEventListener('click', async () => {
    cam.stop();
    after.style.display = 'none'; shotBtn.style.display = 'none';
    let ok = 0;
    for (let i = 0; i < shots.length; i++) {
      msg.textContent = `上傳中 ${i + 1}/${shots.length}…`;
      try { const { status } = await captureUpload(shots[i]); if (status === 202) ok += 1; }
      catch (e) { /* 單張失敗略過，續傳其餘 */ }
    }
    msg.textContent = `已送出 ${ok}/${shots.length} 張，背景辨識中，稍後到暫存區確認`;
    setTimeout(onDone, 1200);
  });
}
