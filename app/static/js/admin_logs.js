import { api } from './admin_api.js';
import { escapeHtml } from './admin_util.js';
import { formatDateTimeTW, action_label } from './audit_util.js';

// 台灣今日（YYYY-MM-DD）
function todayTW() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date());
  return parts; // en-CA 產出 2026-07-09 格式
}

export async function renderLogs(container, identity, storeId) {
  const isSuper = identity.role === 'super_admin';
  if (isSuper && !storeId) {
    container.innerHTML = '<div class="wk-empty">請先於上方選擇一家店</div>';
    return;
  }
  const sid = isSuper ? storeId : null;
  const date = todayTW();
  container.innerHTML = `
    <div class="wk-toolbar-row">
      日期：<input class="wk-input" type="date" id="lg-date" value="${date}" max="${date}">
      員工：<select class="wk-select" id="lg-actor"><option value="">全部</option></select>
    </div>
    <div class="wk-card"><div class="table-wrap"><table class="wk-table"><thead><tr>
      <th>時間</th><th>員工</th><th>單號</th><th>摘要</th><th>動作</th>
    </tr></thead><tbody id="lg-body"></tbody></table></div></div>`;
  const dinp = container.querySelector('#lg-date');
  const asel = container.querySelector('#lg-actor');

  async function load() {
    const body = container.querySelector('#lg-body');
    body.innerHTML = '<tr><td colspan="5">載入中…</td></tr>';
    const actorId = asel.value ? Number(asel.value) : null;
    const { data } = await api.auditLogs(sid, dinp.value, actorId);
    const actors = data.actors || [];
    // 只在第一次填員工下拉（保留當前選擇）
    if (asel.options.length <= 1 && actors.length) {
      asel.innerHTML = '<option value="">全部</option>' +
        actors.map((a) => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join('');
      asel.value = actorId != null ? String(actorId) : '';
    }
    const items = data.items || [];
    body.innerHTML = items.length
      ? items.map((i) => `<tr>
          <td class="au-time" data-label="時間">${formatDateTimeTW(i.ts)}</td>
          <td data-label="員工">${escapeHtml(i.actor_name || '')}</td>
          <td data-label="單號">${escapeHtml(i.doc_no || `#${i.expense_id}`)}</td>
          <td data-label="摘要">${escapeHtml(i.summary || '')}</td>
          <td data-label="動作">${action_label(i.action)}</td>
        </tr>`).join('')
      : '<tr><td colspan="5">當天沒有操作記錄</td></tr>';
  }

  dinp.addEventListener('change', () => { if (dinp.value) load(); });
  asel.addEventListener('change', load);
  load();
}
