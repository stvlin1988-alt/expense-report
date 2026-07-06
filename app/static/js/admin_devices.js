import {
  isValidPin, deviceStatusLabel, sortPendingFirst, roleLabel, escapeHtml,
} from './admin_util.js';

export function renderDevices(container, ctx) {
  const { identity, storeId, stores, api } = ctx;
  const isSuper = identity.role === 'super_admin';

  container.innerHTML = `
    <div id="dev-list">載入中…</div>
    <div class="ap-msg" id="dev-msg"></div>`;
  const msg = container.querySelector('#dev-msg');
  const setMsg = (t, ok) => { msg.textContent = t; msg.style.color = ok ? '#2e7d32' : '#c62828'; };

  async function loadUsers() {
    try {
      const { status, data } = await api.getUsers(isSuper ? storeId : undefined);
      if (status === 200 && data.status === 'ok') return data.users;
    } catch (e) { /* ignore */ }
    return [];
  }

  async function loadList() {
    const listEl = container.querySelector('#dev-list');
    let devices = [];
    try {
      const { status, data } = await api.getDevices(isSuper ? storeId : undefined);
      if (status === 200 && data.status === 'ok') devices = data.devices;
      else { listEl.textContent = '無法載入裝置'; return; }
    } catch (e) { listEl.textContent = '無法載入裝置'; return; }

    const users = await loadUsers();
    const userName = (id) => (users.find((u) => u.id === id) || {}).name || id;

    const rows = sortPendingFirst(devices).map((d) => {
      const label = deviceStatusLabel(d);
      const cls = d.is_revoked ? 'revoked' : (d.is_approved ? 'approved' : 'pending');
      const tail = (d.client_uid || '').slice(-6);
      const bound = d.bound_user_id ? userName(d.bound_user_id) : '—';
      const actions = (!d.is_approved && !d.is_revoked)
        ? `<button class="ap-btn" data-act="approve" type="button">核准</button>`
        : (d.is_approved && !d.is_revoked
            ? `<button class="ap-btn danger" data-act="revoke" type="button">撤銷</button>`
            : '');
      return `
        <tr data-did="${d.id}">
          <td>${escapeHtml(d.device_name || 'Unknown')}</td>
          <td>…${escapeHtml(tail)}</td>
          <td>${d.store_id ?? '—'}</td>
          <td>${escapeHtml(bound)}</td>
          <td><span class="ap-badge ${cls}">${label}</span></td>
          <td class="ap-rowbtns">${actions}</td>
        </tr>`;
    }).join('');

    listEl.innerHTML = `
      <table class="ap-table">
        <thead><tr><th>裝置</th><th>UID</th><th>店</th><th>綁定</th><th>狀態</th><th>操作</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="6">尚無裝置</td></tr>'}</tbody>
      </table>
      <div id="dev-approve-panel"></div>`;

    listEl.querySelectorAll('tr[data-did]').forEach((tr) => {
      const did = parseInt(tr.dataset.did, 10);
      const ap = tr.querySelector('[data-act="approve"]');
      const rv = tr.querySelector('[data-act="revoke"]');
      if (ap) ap.addEventListener('click', () => showApprove(did, users));
      if (rv) rv.addEventListener('click', () => revoke(did));
    });
  }

  function showApprove(did, users) {
    const panel = container.querySelector('#dev-approve-panel');
    const userOpts = users.map((u) => `<option value="${u.id}">${escapeHtml(u.name)}（${roleLabel(u.role)}）</option>`).join('');
    const storeOpts = stores.map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');
    panel.innerHTML = `
      <div class="ap-form" style="flex-direction:column;align-items:stretch;">
        <div><strong>核准裝置 #${did}</strong></div>
        <label><input type="radio" name="ap-mode" value="bind" checked> 綁到現有使用者</label>
        <select id="ap-bind">${userOpts || '<option value="">（無可綁定使用者）</option>'}</select>
        <label><input type="radio" name="ap-mode" value="new"> 建新帳號並綁定</label>
        <div class="ap-form">
          <input type="text" id="ap-nu-name" placeholder="姓名" autocomplete="off">
          <input type="password" id="ap-nu-pw" placeholder="4位密碼" inputmode="numeric" maxlength="4" autocomplete="off">
          ${isSuper ? `<select id="ap-nu-role"><option value="employee">員工</option><option value="manager">店長</option><option value="accountant">會計</option><option value="super_admin">業主</option></select><select id="ap-nu-store">${storeOpts}</select>` : `<input type="hidden" id="ap-nu-role" value="employee">`}
        </div>
        ${isSuper
          ? `<label><input type="radio" name="ap-mode" value="bare"> 裸核准（僅指派店）</label><select id="ap-bare-store">${storeOpts}</select>`
          : `<label><input type="radio" name="ap-mode" value="bare"> 裸核准（歸本店）</label>`}
        <div class="ap-rowbtns">
          <button class="ap-btn" id="ap-confirm" type="button">確認核准</button>
          <button class="ap-btn secondary" id="ap-cancel" type="button">取消</button>
        </div>
      </div>`;
    const pw = panel.querySelector('#ap-nu-pw');
    pw.addEventListener('input', () => { pw.value = pw.value.replace(/\D/g, '').slice(0, 4); });
    panel.querySelector('#ap-cancel').addEventListener('click', () => { panel.innerHTML = ''; });
    panel.querySelector('#ap-confirm').addEventListener('click', () => confirmApprove(did, panel));
  }

  async function confirmApprove(did, panel) {
    const mode = panel.querySelector('input[name="ap-mode"]:checked').value;
    const btn = panel.querySelector('#ap-confirm');
    let payload = {};
    if (mode === 'bind') {
      const v = panel.querySelector('#ap-bind').value;
      if (!v) { setMsg('請選擇使用者', false); return; }
      payload = { bound_user_id: parseInt(v, 10) };
    } else if (mode === 'new') {
      const name = panel.querySelector('#ap-nu-name').value.trim();
      const p = panel.querySelector('#ap-nu-pw').value;
      const role = panel.querySelector('#ap-nu-role').value;
      if (!name) { setMsg('請填姓名', false); return; }
      if (!isValidPin(p)) { setMsg('密碼需為 4 位數字', false); return; }
      const nu = { name, password: p, role };
      if (isSuper) {
        const nuStore = panel.querySelector('#ap-nu-store');
        nu.store_id = nuStore ? parseInt(nuStore.value, 10) : undefined;
      }
      payload = { new_user: nu };
    } else if (mode === 'bare') {
      const bareStore = panel.querySelector('#ap-bare-store');
      payload = bareStore ? { store_id: parseInt(bareStore.value, 10) } : {};
    }
    if (btn) btn.disabled = true;
    try {
      const { status, data } = await api.approveDevice(did, payload);
      if (status === 200 && data.status === 'ok') { setMsg('已核准（換機會自動撤舊）', true); panel.innerHTML = ''; await loadList(); }
      else if (status === 403) { setMsg('無權限', false); if (btn) btn.disabled = false; }
      else { setMsg('核准失敗（' + (data.message || '') + '）', false); if (btn) btn.disabled = false; }
    } catch (e) { setMsg('核准失敗，請重試', false); if (btn) btn.disabled = false; }
  }

  async function revoke(did) {
    if (!confirm('確定撤銷此裝置？')) return;
    try {
      const { status, data } = await api.revokeDevice(did);
      if (status === 200 && data.status === 'ok') { setMsg('已撤銷', true); await loadList(); }
      else if (status === 403) setMsg('無權限', false);
      else setMsg('撤銷失敗', false);
    } catch (e) { setMsg('撤銷失敗，請重試', false); }
  }

  loadList();
}
