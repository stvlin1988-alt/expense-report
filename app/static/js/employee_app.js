// 員工手機殼（UI 重塑 2026-07）：抬頭 + 3 pane 內容區 + 底部 tab bar。
// 取代員工登入後原本逐頁 .modal-box 疊層流程（auth.js showAppView，非員工 fallback 仍保留）。
// pane 內容：拍單（Task 2 capture.js renderShootPane）、確認區（Task 3 pending.js renderConfirmPane）
// 已接上；複查 pane 留給 Task 5（review.js renderReviewPane）。
import { Camera } from './camera.js';
import { escapeHtml } from './admin_util.js';
import { renderShootPane } from './capture.js';
import { renderConfirmPane } from './pending.js';

const root = () => document.getElementById('modal-root');

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  return { status: res.status, data: await res.json().catch(() => ({})) };
}

let toastTimer = null;
// 供 Task 2/3/5 的 pane 模組 import 使用：`import { mbToast } from './employee_app.js';`
export function mbToast(msg) {
  const el = document.getElementById('mb-toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

// 切走 pane 前停止該 pane 容器內任何 live 相機串流（影像不落地）。
// 沿用 admin.js:320-323 的 querySelector('video') + srcObject.getTracks().stop() pattern。
function stopPaneCamera(container) {
  if (!container) return;
  container.querySelectorAll('video').forEach((v) => {
    if (v.srcObject) {
      v.srcObject.getTracks().forEach((t) => t.stop());
      v.srcObject = null;
    }
  });
}

export function showEmployeeApp(identity) {
  const store = identity.store_code || ''; // identity 現無 store_code，店徽不顯示（不造假、不動後端）
  root().innerHTML = `
    <div class="mb-app" id="mb-app">
      <header class="mb-appbar">
        <div class="mb-who">
          ${store ? `<span class="mb-store-badge">${escapeHtml(store)}</span>` : ''}
          <span><span class="mb-name">${escapeHtml(identity.name)}</span><span class="mb-sub">員工</span></span>
        </div>
        <div class="mb-orient" role="group" aria-label="拍攝方向">
          <button type="button" id="mb-opt-portrait" aria-pressed="true">直式</button>
          <button type="button" id="mb-opt-landscape" aria-pressed="false">橫式</button>
        </div>
        <div class="mb-appbar-actions">
          <button class="mb-icon-btn" id="mb-reface" title="更新人臉" aria-label="更新人臉">🙂</button>
          <button class="mb-icon-btn" id="mb-logout" title="登出" aria-label="登出">⎋</button>
        </div>
      </header>
      <main class="mb-content">
        <section class="mb-pane active" id="mb-pane-shoot" aria-label="拍單"></section>
        <section class="mb-pane" id="mb-pane-confirm" aria-label="確認區"></section>
        <section class="mb-pane" id="mb-pane-review" aria-label="複查"></section>
      </main>
      <nav class="mb-tabbar" aria-label="主功能">
        <button class="mb-tab active" data-tab="shoot" type="button">拍單</button>
        <button class="mb-tab" data-tab="confirm" type="button">確認區<span class="mb-badge zero" id="mb-confirm-badge">0</span></button>
        <button class="mb-tab" data-tab="review" type="button">複查</button>
      </nav>
      <div class="mb-toast" id="mb-toast" role="status" aria-live="polite"></div>
    </div>`;

  const panes = {
    shoot: document.getElementById('mb-pane-shoot'),
    confirm: document.getElementById('mb-pane-confirm'),
    review: document.getElementById('mb-pane-review'),
  };
  let activeTab = 'shoot';

  function showTab(name) {
    if (!panes[name] || name === activeTab) return;
    // 切走目前 pane 前先停該 pane 內的相機串流（Task 2 拍單 pane 會有 live getUserMedia）。
    stopPaneCamera(panes[activeTab]);
    activeTab = name;
    document.querySelectorAll('.mb-tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
    Object.entries(panes).forEach(([k, el]) => el.classList.toggle('active', k === name));
    renderPane(name);
  }

  function renderPane(name) {
    // Task 5 落地時的呼叫慣例（沿承 brief）：review: renderReviewPane(panes.review)
    if (name === 'shoot') {
      renderShootPane(panes.shoot, { onUploaded: () => { showTab('confirm'); } });
    } else if (name === 'confirm') {
      renderConfirmPane(panes.confirm, { onCountChange: setConfirmBadge });
    }
  }

  // 供 Task 3 renderConfirmPane 的 onCountChange 回呼沿用；Task 1 先定義、殼本身不驅動內容。
  function setConfirmBadge(n) {
    const b = document.getElementById('mb-confirm-badge');
    if (!b) return;
    b.textContent = String(n);
    b.classList.toggle('zero', !n);
  }

  document.querySelectorAll('.mb-tab').forEach((t) => t.addEventListener('click', () => showTab(t.dataset.tab)));

  // 直橫切換：切 .land（Task 2 有橫式 CSS），停在當前 tab
  const setLand = (land) => {
    document.getElementById('mb-app').classList.toggle('land', land);
    document.getElementById('mb-opt-portrait').setAttribute('aria-pressed', String(!land));
    document.getElementById('mb-opt-landscape').setAttribute('aria-pressed', String(land));
  };
  document.getElementById('mb-opt-portrait').addEventListener('click', () => setLand(false));
  document.getElementById('mb-opt-landscape').addEventListener('click', () => setLand(true));

  // 登出
  document.getElementById('mb-logout').addEventListener('click', async () => {
    stopPaneCamera(panes[activeTab]);
    await postJSON('/auth/logout');
    location.reload();
  });

  // 更新人臉：沿用 auth.js showAppView 49-74 的兩段式流程（記憶體相機，影像不落地）
  wireReface();

  renderPane('shoot'); // 進站預設拍單（pane 已是 active，這裡只補呼叫慣例）
}

function wireReface() {
  const btn = document.getElementById('mb-reface');
  if (!btn) return;

  // 隱藏 video/canvas：不落地、只在記憶體內拍一張人臉照
  const video = document.createElement('video');
  video.id = 'mb-reface-video';
  video.autoplay = true;
  video.playsInline = true;
  video.muted = true;
  video.style.display = 'none';
  const canvas = document.createElement('canvas');
  canvas.id = 'mb-reface-canvas';
  canvas.style.display = 'none';
  document.getElementById('mb-app').appendChild(video);
  document.getElementById('mb-app').appendChild(canvas);

  const cam = new Camera(video, canvas);

  btn.addEventListener('click', async () => {
    if (!cam.isRecording) {
      try {
        await cam.start();
        video.style.display = 'block';
        mbToast('請對準鏡頭，再按一次「更新人臉」');
      } catch (e) {
        mbToast('無法開啟鏡頭');
      }
      return;
    }
    try {
      const face = cam.capture();
      const { data } = await postJSON('/face/enroll', { face_image: face });
      mbToast(data.status === 'ok' ? '人臉已更新' : '更新失敗，請重試');
    } catch (e) {
      mbToast('更新失敗，請重試');
    } finally {
      // 無論成功或失敗都關鏡頭：影像不落地
      cam.stop();
      video.style.display = 'none';
    }
  });
}
