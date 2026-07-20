import { Camera } from './camera.js';
import { captureUpload } from './expenses_api.js';
import { mbToast } from './employee_app.js';

// 拍單 pane：取景框 + 快門 + 多拍 + 上傳進度。渲染進 container（員工手機殼 pane 容器）。
// 影像不落地：getUserMedia + canvas，base64 只存記憶體，逐張 POST 後即捨棄。
export function renderShootPane(container, { onUploaded } = {}) {
  container.innerHTML = `
    <div class="mb-viewfinder">
      <span class="mb-shot-count" id="mb-shot-count">已拍 0 張</span>
      <div class="mb-vf-frame" aria-hidden="true"><b></b></div>
      <p class="mb-vf-hint">將單據對準框內，光線充足、拍清楚金額</p>
      <div class="mb-vf-flash" id="mb-vf-flash" aria-hidden="true"></div>
      <video id="mb-cap-video" autoplay playsinline muted style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:-1"></video>
      <canvas id="mb-cap-canvas" style="display:none"></canvas>
    </div>
    <div class="mb-cam-dock" id="mb-cam-dock">
      <div class="mb-cam-side"><button class="mb-btn mb-btn-ghost mb-btn-sm" id="mb-next" type="button">下一張</button></div>
      <button class="mb-shutter" id="mb-shutter" aria-label="快門" type="button"></button>
      <div class="mb-cam-side"><button class="mb-btn mb-btn-primary mb-btn-sm" id="mb-finish" type="button">完成</button></div>
    </div>
    <div class="mb-upload-panel" id="mb-upload">
      <div id="mb-upl-progress"><p class="mb-upl-line" id="mb-upl-line">上傳中…</p><div class="mb-upl-bar"><i id="mb-upl-fill"></i></div></div>
      <div class="mb-upl-done" id="mb-upl-done"><span class="ok-chip" id="mb-upl-chip"></span>
        <p class="big">背景辨識中，稍後到「確認區」確認</p>
        <button class="mb-btn mb-btn-primary" id="mb-go-confirm" type="button" style="width:100%">前往確認區</button>
        <button class="mb-btn mb-btn-ghost mb-btn-sm" id="mb-shoot-again" type="button" style="width:100%">繼續拍下一批</button></div>
    </div>`;

  const cam = new Camera(container.querySelector('#mb-cap-video'), container.querySelector('#mb-cap-canvas'));
  const shots = [];
  cam.start().catch(() => mbToast('無法開啟鏡頭'));

  const flash = () => {
    const f = container.querySelector('#mb-vf-flash');
    f.classList.remove('on'); void f.offsetWidth; f.classList.add('on');
  };

  container.querySelector('#mb-shutter').addEventListener('click', () => {
    if (!cam.isRecording) return;
    shots.push(cam.capture()); flash();                      // base64 記憶體、不落地
    container.querySelector('#mb-shot-count').textContent = `已拍 ${shots.length} 張`;
  });
  container.querySelector('#mb-next').addEventListener('click', () => mbToast('請拍下一張'));
  container.querySelector('#mb-finish').addEventListener('click', async () => {
    if (!shots.length) { mbToast('還沒拍任何單據'); return; }
    cam.stop();
    container.querySelector('#mb-cam-dock').style.display = 'none';
    container.querySelector('#mb-upload').classList.add('show');
    const fill = container.querySelector('#mb-upl-fill');
    const line = container.querySelector('#mb-upl-line');
    let ok = 0;
    for (let i = 0; i < shots.length; i++) {
      line.textContent = `上傳中 ${i + 1}/${shots.length}…`;
      try { const { status } = await captureUpload(shots[i]); if (status === 202) ok += 1; } catch (e) { /* 單張失敗略過，續傳其餘 */ }
      fill.style.width = `${((i + 1) / shots.length) * 100}%`;
    }
    container.querySelector('#mb-upl-progress').style.display = 'none';
    container.querySelector('#mb-upl-chip').textContent = `✓ 已送出 ${ok}/${shots.length} 張`;
    container.querySelector('#mb-upl-done').classList.add('show');
  });
  container.querySelector('#mb-go-confirm').addEventListener('click', () => { if (onUploaded) onUploaded(); });
  container.querySelector('#mb-shoot-again').addEventListener('click', () => renderShootPane(container, { onUploaded }));
}
