import { Camera } from './camera.js';
import {
  isValidPin, roleLabel, filterByStore, escapeHtml,
} from './admin_util.js';

export function renderAccounts(container, ctx) {
  const { identity, storeId, stores, api } = ctx;
  const isSuper = identity.role === 'super_admin';

  container.innerHTML = `
    <div id="acc-list">載入中…</div>
    <div class="wk-card" id="acc-create"></div>
    <div class="wk-msg" id="acc-msg"></div>
    <video id="acc-video" autoplay playsinline muted class="ap-video" style="display:none;"></video>
    <canvas id="acc-canvas" style="display:none;"></canvas>`;

  const msg = container.querySelector('#acc-msg');
  const video = container.querySelector('#acc-video');
  const canvas = container.querySelector('#acc-canvas');
  const cam = new Camera(video, canvas);
  let pendingFace = null;  // 建帳號時一併擷取的人臉（建立後套用），影像不落地

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

    const storeMap = Object.fromEntries(stores.map((s) => [s.id, s.code]));
    const ROLE_KEYS = ['employee', 'manager', 'accountant', 'super_admin'];

    // 角色欄：經理(super_admin)可改他人角色（不可改自己）；否則靜態顯示
    function roleCell(u) {
      if (!isSuper || u.id === identity.id) return roleLabel(u.role);
      const opts = ROLE_KEYS.map((r) =>
        `<option value="${r}"${r === u.role ? ' selected' : ''}>${escapeHtml(roleLabel(r))}</option>`).join('');
      return `<select data-rolesel="${u.id}">${opts}</select>`;
    }
    // 店欄：經理可改任何人；主管可改本店員工＋自己（後端 _manages / 自己 把關）。目標店任選。
    function storeCell(u) {
      const canEdit = isSuper || u.role === 'employee' || u.id === identity.id;
      if (!canEdit) {
        return escapeHtml(u.store_id != null ? String(storeMap[u.store_id] || u.store_id) : '—');
      }
      const nullOpt = isSuper ? `<option value=""${u.store_id == null ? ' selected' : ''}>（無）</option>` : '';
      const opts = stores.map((s) =>
        `<option value="${s.id}"${s.id === u.store_id ? ' selected' : ''}>${escapeHtml(s.code)}</option>`).join('');
      return `<select data-storesel="${u.id}">${nullOpt}${opts}</select>`;
    }

    // super_admin 選了店 → 後端已過濾；未選店時前端不再過濾（回全部）
    const rows = filterByStore(users, isSuper ? storeId : null).map((u) => {
      const face = u.has_face ? '有' : '—';
      const activeBadge = u.active ? '' : '<span class="wk-badge wk-badge-neutral">停用</span>';
      return `
        <tr data-uid="${u.id}" data-role="${u.role}" data-active="${u.active}">
          <td data-label="姓名">${escapeHtml(u.name)} ${activeBadge}</td>
          <td data-label="角色">${roleCell(u)}</td>
          <td data-label="店">${storeCell(u)}</td>
          <td data-label="臉">${face}</td>
          <td class="wk-rowbtns">
            <button class="wk-btn wk-btn-secondary" data-act="pw" type="button">改密碼</button>
            <button class="wk-btn wk-btn-secondary" data-act="face" type="button">錄臉</button>
            <button class="wk-btn ${u.active ? 'wk-btn-danger-soft' : 'wk-btn-secondary'}" data-act="active" type="button">${u.active ? '停用' : '復用'}</button>
          </td>
        </tr>`;
    }).join('');

    listEl.innerHTML = `
      <div class="wk-card"><div class="table-wrap">
        <table class="wk-table">
          <thead><tr><th>姓名</th><th>角色</th><th>店</th><th>臉</th><th>操作</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="5">尚無帳號</td></tr>'}</tbody>
        </table>
      </div></div>`;

    listEl.querySelectorAll('tr[data-uid]').forEach((tr) => {
      const uid = parseInt(tr.dataset.uid, 10);
      tr.querySelector('[data-act="pw"]').addEventListener('click', () => resetPw(uid));
      tr.querySelector('[data-act="face"]').addEventListener('click', () => enrollFace(uid));
      tr.querySelector('[data-act="active"]').addEventListener('click', () =>
        toggleActive(uid, tr.dataset.active !== 'true'));
    });

    listEl.querySelectorAll('select[data-storesel]').forEach((sel) => {
      sel.addEventListener('change', async () => {
        const uid = parseInt(sel.dataset.storesel, 10);
        const val = sel.value ? parseInt(sel.value, 10) : null;
        try {
          const { status, data } = await api.setUserStore(uid, val);
          if (status === 200 && data.status === 'ok') { setMsg('已更新店別', true); await loadList(); }
          else if (status === 403) setMsg('無權限', false);
          else setMsg('更新店別失敗', false);
        } catch (e) { setMsg('更新店別失敗，請重試', false); }
      });
    });

    listEl.querySelectorAll('select[data-rolesel]').forEach((sel) => {
      sel.addEventListener('change', async () => {
        const uid = parseInt(sel.dataset.rolesel, 10);
        try {
          const { status, data } = await api.setUserRole(uid, sel.value);
          if (status === 200 && data.status === 'ok') { setMsg('已更新角色', true); await loadList(); }
          else if (status === 400) setMsg(data.message === 'cannot change own role' ? '不能改自己的角色' : '不能把最後一位經理降級', false);
          else if (status === 403) setMsg('無權限', false);
          else setMsg('更新角色失敗', false);
        } catch (e) { setMsg('更新角色失敗，請重試', false); }
      });
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
      else if (status === 400) setMsg(data.message === 'cannot deactivate self' ? '不能停用自己' : '不能停用最後一位經理', false);
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

  function resetFaceCapture() {
    pendingFace = null;
    const st = container.querySelector('#acc-cap-status');
    if (st) { st.textContent = '未錄臉'; st.style.color = '#888'; }
    const capBtn = container.querySelector('#acc-cap');
    if (capBtn) capBtn.textContent = '錄臉';
  }

  // 新增帳號表單內的錄臉：第一次按開相機，第二次按擷取（存 pendingFace，建立後套用）
  async function captureForCreate() {
    const st = container.querySelector('#acc-cap-status');
    const capBtn = container.querySelector('#acc-cap');
    if (!cam.isRecording) {
      try {
        await cam.start();
        video.style.display = 'block';
        capBtn.textContent = '拍攝';
        st.textContent = '對準鏡頭後按「拍攝」'; st.style.color = '#888';
      } catch (e) { st.textContent = '無法開啟鏡頭'; st.style.color = '#c62828'; }
      return;
    }
    pendingFace = cam.capture();
    cam.stop(); video.style.display = 'none';  // 影像不落地：擷取後即關鏡頭
    capBtn.textContent = '重拍';
    st.textContent = '✓ 已擷取（建立後套用）'; st.style.color = '#2e7d32';
  }

  function renderCreateForm() {
    const createEl = container.querySelector('#acc-create');
    const roleSel = isSuper
      ? `<select class="wk-select" id="acc-role">
           <option value="employee">員工</option>
           <option value="manager">主管</option>
           <option value="accountant">會計</option>
           <option value="super_admin">經理</option>
         </select>`
      : `<input type="hidden" id="acc-role" value="employee"><span>員工</span>`;
    const storeSel = isSuper
      ? `<select class="wk-select" id="acc-store">
           ${stores.map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('')}
         </select>`
      : '';
    createEl.innerHTML = `
      <div class="wk-card-body wk-toolbar-row">
        <input class="wk-input" type="text" id="acc-name" placeholder="姓名" autocomplete="off">
        <input class="wk-input" type="password" id="acc-pw" placeholder="4位密碼" inputmode="numeric" maxlength="4" autocomplete="off">
        ${roleSel} ${storeSel}
        <button class="wk-btn wk-btn-secondary" id="acc-cap" type="button">錄臉</button>
        <span class="ap-face-status" id="acc-cap-status" style="color:#888;">未錄臉</span>
        <button class="wk-btn wk-btn-primary" id="acc-add" type="button">建立帳號</button>
      </div>`;
    const pw = createEl.querySelector('#acc-pw');
    pw.addEventListener('input', () => { pw.value = pw.value.replace(/\D/g, '').slice(0, 4); });
    createEl.querySelector('#acc-cap').addEventListener('click', captureForCreate);
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
        // 若表單已擷取人臉，一併錄到新帳號
        if (pendingFace && data.id) {
          try {
            const fr = await api.enrollFace(data.id, pendingFace);
            if (fr.status === 200 && fr.data.status === 'ok') setMsg('已建立帳號並錄臉', true);
            else if (fr.data && fr.data.status === 'face_not_found') setMsg('帳號已建立，但未偵測到人臉；可在清單列「錄臉」重錄', false);
            else setMsg('帳號已建立，但錄臉失敗；可在清單列「錄臉」重錄', false);
          } catch (e2) { setMsg('帳號已建立，但錄臉失敗；可在清單列「錄臉」重錄', false); }
        } else {
          setMsg('已建立帳號', true);
        }
        container.querySelector('#acc-name').value = '';
        container.querySelector('#acc-pw').value = '';
        resetFaceCapture();
        await loadList();
      } else if (status === 403) setMsg('無權限', false);
      else setMsg('建立失敗（' + (data.message || '') + '）', false);
    } catch (e) { setMsg('建立失敗，請重試', false); }
  }

  renderCreateForm();
  loadList();
}
