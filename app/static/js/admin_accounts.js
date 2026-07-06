import { Camera } from './camera.js';
import { isValidPin, roleLabel, filterByStore } from './admin_util.js';

export function renderAccounts(container, ctx) {
  const { identity, storeId, stores, api } = ctx;
  const isSuper = identity.role === 'super_admin';

  container.innerHTML = `
    <div id="acc-list">載入中…</div>
    <div class="ap-form" id="acc-create"></div>
    <div class="ap-msg" id="acc-msg"></div>
    <video id="acc-video" autoplay playsinline muted class="ap-video" style="display:none;"></video>
    <canvas id="acc-canvas" style="display:none;"></canvas>`;

  const msg = container.querySelector('#acc-msg');
  const video = container.querySelector('#acc-video');
  const canvas = container.querySelector('#acc-canvas');
  const cam = new Camera(video, canvas);

  function setMsg(text, ok) {
    msg.textContent = text;
    msg.style.color = ok ? '#2e7d32' : '#c62828';
  }

  async function loadList() {
    const listEl = container.querySelector('#acc-list');
    let users = [];
    try {
      const { status, data } = await api.getUsers(isSuper ? storeId : undefined);
      if (status === 200 && data.status === 'ok') users = data.users;
      else { listEl.textContent = '無法載入帳號'; return; }
    } catch (e) { listEl.textContent = '無法載入帳號'; return; }

    // super_admin 選了店 → 後端已過濾；未選店時前端不再過濾（回全部）
    const rows = filterByStore(users, isSuper ? storeId : null).map((u) => {
      const face = u.has_face ? '有' : '—';
      const activeBadge = u.active ? '' : '<span class="ap-badge inactive">停用</span>';
      return `
        <tr data-uid="${u.id}" data-role="${u.role}" data-active="${u.active}">
          <td>${u.name} ${activeBadge}</td>
          <td>${roleLabel(u.role)}</td>
          <td>${u.store_id ?? '—'}</td>
          <td>${face}</td>
          <td class="ap-rowbtns">
            <button class="ap-btn" data-act="pw" type="button">改密碼</button>
            <button class="ap-btn secondary" data-act="face" type="button">錄臉</button>
            <button class="ap-btn ${u.active ? 'danger' : ''}" data-act="active" type="button">${u.active ? '停用' : '復用'}</button>
          </td>
        </tr>`;
    }).join('');

    listEl.innerHTML = `
      <table class="ap-table">
        <thead><tr><th>姓名</th><th>角色</th><th>店</th><th>臉</th><th>操作</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5">尚無帳號</td></tr>'}</tbody>
      </table>`;

    listEl.querySelectorAll('tr[data-uid]').forEach((tr) => {
      const uid = parseInt(tr.dataset.uid, 10);
      tr.querySelector('[data-act="pw"]').addEventListener('click', () => resetPw(uid));
      tr.querySelector('[data-act="face"]').addEventListener('click', () => enrollFace(uid));
      tr.querySelector('[data-act="active"]').addEventListener('click', () =>
        toggleActive(uid, tr.dataset.active !== 'true'));
    });
  }

  async function resetPw(uid) {
    const pin = prompt('輸入新的 4 位數字密碼');
    if (pin == null) return;
    if (!isValidPin(pin)) { setMsg('密碼需為 4 位數字', false); return; }
    try {
      const { status, data } = await api.resetPassword(uid, pin);
      if (status === 200 && data.status === 'ok') setMsg('已重設密碼', true);
      else if (status === 403) setMsg('無權限', false);
      else setMsg('重設失敗', false);
    } catch (e) { setMsg('重設失敗，請重試', false); }
  }

  async function toggleActive(uid, active) {
    try {
      const { status, data } = await api.setActive(uid, active);
      if (status === 200 && data.status === 'ok') { await loadList(); setMsg(active ? '已復用' : '已停用', true); }
      else if (status === 400) setMsg(data.message === 'cannot deactivate self' ? '不能停用自己' : '不能停用最後一位業主', false);
      else if (status === 403) setMsg('無權限', false);
      else setMsg('操作失敗', false);
    } catch (e) { setMsg('操作失敗，請重試', false); }
  }

  async function enrollFace(uid) {
    setMsg('', true);
    if (!cam.isRecording) {
      try {
        await cam.start();
        video.style.display = 'block';
        setMsg('請對準該員工鏡頭，再按一次「錄臉」', true);
      } catch (e) { setMsg('無法開啟鏡頭', false); }
      return;
    }
    try {
      const face = cam.capture();
      const { status, data } = await api.enrollFace(uid, face);
      if (status === 200 && data.status === 'ok') { setMsg('已錄臉', true); await loadList(); }
      else if (status === 403) setMsg('無權限', false);
      else if (data.status === 'face_not_found') setMsg('未偵測到人臉，請重試', false);
      else setMsg('錄臉失敗', false);
    } catch (e) { setMsg('錄臉失敗，請重試', false); }
    finally { cam.stop(); video.style.display = 'none'; }  // 影像不落地
  }

  function renderCreateForm() {
    const createEl = container.querySelector('#acc-create');
    const roleSel = isSuper
      ? `<select id="acc-role">
           <option value="employee">員工</option>
           <option value="manager">店長</option>
           <option value="accountant">會計</option>
           <option value="super_admin">業主</option>
         </select>`
      : `<input type="hidden" id="acc-role" value="employee"><span>員工</span>`;
    const storeSel = isSuper
      ? `<select id="acc-store">
           ${stores.map((s) => `<option value="${s.id}">${s.name}</option>`).join('')}
         </select>`
      : '';
    createEl.innerHTML = `
      <input type="text" id="acc-name" placeholder="姓名" autocomplete="off">
      <input type="password" id="acc-pw" placeholder="4位密碼" inputmode="numeric" maxlength="4" autocomplete="off">
      ${roleSel} ${storeSel}
      <button class="ap-btn" id="acc-add" type="button">建立帳號</button>`;
    const pw = createEl.querySelector('#acc-pw');
    pw.addEventListener('input', () => { pw.value = pw.value.replace(/\D/g, '').slice(0, 4); });
    createEl.querySelector('#acc-add').addEventListener('click', createUser);
  }

  async function createUser() {
    setMsg('', true);
    const name = container.querySelector('#acc-name').value.trim();
    const pw = container.querySelector('#acc-pw').value;
    const role = container.querySelector('#acc-role').value;
    if (!name) { setMsg('請填姓名', false); return; }
    if (!isValidPin(pw)) { setMsg('密碼需為 4 位數字', false); return; }
    const payload = { name, password: pw, role };
    if (isSuper) {
      const storeEl = container.querySelector('#acc-store');
      if (!storeEl || !storeEl.value) { setMsg('請選擇店別', false); return; }
      payload.store_id = parseInt(storeEl.value, 10);
    } else {
      payload.role = 'employee';
      payload.store_id = identity.store_id; // 由 index 注入；缺則後端擋
    }
    try {
      const { status, data } = await api.createUser(payload);
      if (status === 200 && data.status === 'ok') {
        setMsg('已建立帳號', true);
        container.querySelector('#acc-name').value = '';
        container.querySelector('#acc-pw').value = '';
        await loadList();
      } else if (status === 403) setMsg('無權限', false);
      else setMsg('建立失敗（' + (data.message || '') + '）', false);
    } catch (e) { setMsg('建立失敗，請重試', false); }
  }

  renderCreateForm();
  loadList();
}
