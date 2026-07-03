import { Camera } from './camera.js';

const root = () => document.getElementById('modal-root');

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  return { status: res.status, data: await res.json().catch(() => ({})) };
}

function openBootstrap() {
  root().innerHTML = `
    <div class="modal-backdrop" id="bs-backdrop">
      <div class="modal-box">
        <h2>首次設定</h2>
        <input type="text" id="bs-name" placeholder="姓名" autocomplete="off">
        <input type="password" id="bs-pw" placeholder="密碼" autocomplete="off">
        <video id="bs-video" autoplay playsinline muted></video>
        <canvas id="bs-canvas" style="display:none;"></canvas>
        <button class="modal-btn" id="bs-submit" type="button">建立並登入</button>
        <div class="modal-msg" id="bs-msg"></div>
      </div>
    </div>`;

  const cam = new Camera(document.getElementById('bs-video'), document.getElementById('bs-canvas'));
  const msg = document.getElementById('bs-msg');
  cam.start().catch(() => { msg.textContent = '無法開啟鏡頭'; });

  document.getElementById('bs-backdrop').addEventListener('click', (ev) => {
    if (ev.target === ev.currentTarget) { cam.stop(); root().innerHTML = ''; }
  });

  document.getElementById('bs-submit').addEventListener('click', async () => {
    const btn = document.getElementById('bs-submit');
    btn.disabled = true; msg.textContent = '';
    const face = cam.isRecording ? cam.capture() : null;
    try {
      const { data } = await postJSON('/auth/bootstrap', {
        name: document.getElementById('bs-name').value.trim(),
        password: document.getElementById('bs-pw').value,
        face_image: face,
      });
      if (data.status === 'ok') {
        msg.style.color = '#4cd964'; msg.textContent = '完成，正在進入…';
        cam.stop();
        setTimeout(() => location.reload(), 800);
        return;
      }
      if (data.status === 'face_not_found') msg.textContent = '未偵測到人臉，請對準鏡頭重試';
      else if (data.status === 'error') msg.textContent = '請填寫姓名與密碼';
      else if (data.status === 'already_initialized') { setTimeout(() => location.reload(), 500); }
      else msg.textContent = '設定失敗，請重試';
      btn.disabled = false;
    } catch (e) {
      // 真網路故障（fetch reject）：中性重試訊息 + 恢復可重試
      msg.style.color = '#ff6b6b';
      msg.textContent = '設定失敗，請重試';
      btn.disabled = false;
    }
  });
}

window.__openBootstrap = openBootstrap;
