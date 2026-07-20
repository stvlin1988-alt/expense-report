import { Camera } from './camera.js';
import { showAdminPanel } from './admin.js';
import { showReconcilePanel } from './reconcile.js';
import { escapeHtml } from './admin_util.js';
import { showReviewView } from './review.js';
import { showEmployeeApp } from './employee_app.js';

const NEUTRAL_MSG = '無法計算，請重試';
const root = () => document.getElementById('modal-root');

function clearRoot() { root().innerHTML = ''; }

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  return { status: res.status, data: await res.json().catch(() => ({})) };
}

// 登入後占位畫面（前端 view state，不換網址）
export function showAppView(identity) {
  clearRoot();
  const roleZh = { employee: '員工', manager: '主管', accountant: '會計', super_admin: '經理' };
  const isEmployee = identity.role === 'employee';
  root().innerHTML = `
    <div class="modal-backdrop">
      <div class="modal-box">
        <h2>已登入</h2>
        <div class="app-view-info">
          姓名：${escapeHtml(identity.name)}<br>身分：${roleZh[identity.role] || identity.role}
        </div>
        <video id="av-video" autoplay playsinline muted style="display:none;"></video>
        <canvas id="av-canvas" style="display:none;"></canvas>
        ${isEmployee ? '<button class="modal-btn" id="av-review" type="button">複查</button>' : ''}
        <button class="modal-btn secondary" id="av-reface" type="button">更新人臉</button>
        <div class="modal-msg" id="av-msg" style="color:#4cd964;"></div>
        <button class="modal-btn" id="av-logout" type="button" style="margin-top:10px;">登出</button>
      </div>
    </div>`;

  const cam = new Camera(document.getElementById('av-video'), document.getElementById('av-canvas'));
  const msg = document.getElementById('av-msg');

  document.getElementById('av-reface').addEventListener('click', async () => {
    if (!cam.isRecording) {
      try {
        await cam.start();
        document.getElementById('av-video').style.display = 'block';
        msg.textContent = '請對準鏡頭，再按一次「更新人臉」';
      } catch (e) {
        msg.textContent = '無法開啟鏡頭';
        msg.style.color = '#ff6b6b';
      }
      return;
    }
    try {
      const face = cam.capture();
      const { data } = await postJSON('/face/enroll', { face_image: face });
      msg.textContent = data.status === 'ok' ? '人臉已更新' : '更新失敗，請重試';
      msg.style.color = data.status === 'ok' ? '#4cd964' : '#ff6b6b';
    } catch (e) {
      msg.textContent = '更新失敗，請重試';
      msg.style.color = '#ff6b6b';
    } finally {
      // 無論成功或失敗都關鏡頭：影像不落地
      cam.stop();
      document.getElementById('av-video').style.display = 'none';
    }
  });

  document.getElementById('av-logout').addEventListener('click', async () => {
    cam.stop();
    await postJSON('/auth/logout');
    location.reload();
  });

  if (isEmployee) {
    document.getElementById('av-review').addEventListener('click', () => {
      cam.stop();
      showReviewView(() => showAppView(identity));
    });
  }
}

function loginModal() {
  clearRoot();
  root().innerHTML = `
    <div class="modal-backdrop" id="auth-backdrop">
      <div class="modal-box">
        <h2>　</h2>
        <video id="m-video" autoplay playsinline muted></video>
        <canvas id="m-canvas" style="display:none;"></canvas>
        <input type="password" id="m-pw" placeholder="密碼" inputmode="numeric" maxlength="4" autocomplete="off">
        <button class="modal-btn" id="m-submit" type="button">確定</button>
        <div class="modal-msg" id="m-msg"></div>
      </div>
    </div>`;
  return {
    video: document.getElementById('m-video'),
    canvas: document.getElementById('m-canvas'),
    pw: document.getElementById('m-pw'),
    submit: document.getElementById('m-submit'),
    msg: document.getElementById('m-msg'),
    backdrop: document.getElementById('auth-backdrop'),
  };
}

async function openLoginFlow() {
  const el = loginModal();
  const cam = new Camera(el.video, el.canvas);

  try { await cam.start(); } catch (e) { /* 無鏡頭：仍可送出，後端回無害訊息 */ }

  el.pw.addEventListener('input', () => { el.pw.value = el.pw.value.replace(/\D/g, '').slice(0, 4); });

  // 背景點擊關閉
  el.backdrop.addEventListener('click', (ev) => {
    if (ev.target === el.backdrop) { cam.stop(); clearRoot(); }
  });

  async function submit() {
    el.submit.disabled = true;
    el.msg.textContent = '';
    const face = cam.isRecording ? cam.capture() : null;
    try {
      const { data } = await postJSON('/auth/verify', {
        password: el.pw.value, face_image: face,
      });
      if (data.status === 'ok') {
        cam.stop();
        const identity = { id: data.id, name: data.name, role: data.role, store_id: data.store_id ?? null };
        if (data.role === 'accountant') showReconcilePanel(identity);
        else if (data.role === 'manager' || data.role === 'super_admin') showAdminPanel(identity);
        else if (data.role === 'employee') showEmployeeApp(identity);
        else showAppView(identity);
        return;
      }
      // 其餘一律隱蔽
      el.msg.textContent = NEUTRAL_MSG;
      el.submit.disabled = false;
    } catch (e) {
      // 真網路故障（fetch reject）：隱蔽提示 + 恢復可重試
      el.msg.textContent = NEUTRAL_MSG;
      el.submit.disabled = false;
    }
  }

  el.submit.addEventListener('click', submit);
  el.pw.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
}

export function openAuth(seedMode) {
  if (seedMode) {
    if (window.__openBootstrap) window.__openBootstrap();  // Task 12
    else openLoginFlow();
    return;
  }
  openLoginFlow();
}
