import { escapeHtml } from './admin_util.js';

export function formatMoney(n) {
  const num = Number(n) || 0;
  return num.toLocaleString('en-US');
}

export function formatDateTimeTW(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Taipei', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(d);
  const g = (t) => (parts.find((x) => x.type === t) || {}).value;
  return `${g('month')}/${g('day')} ${g('hour')}:${g('minute')}`;
}

export function action_label(action) {
  if (action === 'edit') return '修改';
  if (action === 'check') return '簽核';
  return action || '';
}

const STATUS_LABELS = {
  submitted: '待稽核',
  audited: '已稽核',
  reconciled: '已核銷',
  rejected: '會計退回',
};

export function status_label(status) {
  return STATUS_LABELS[status] || status || '';
}

function fmtVal(v) {
  return (v === null || v === undefined || v === '') ? '（空）' : String(v);
}

export function renderTrailRows(logs) {
  if (!logs || !logs.length) return '<div class="au-trail-empty">無修改記錄</div>';
  return logs.map((l) => {
    const detail = (l.changes || [])
      .map((c) => `${escapeHtml(c.field)} ${escapeHtml(fmtVal(c.from))}→${escapeHtml(fmtVal(c.to))}`)
      .join('；');
    const suffix = detail ? `：${detail}` : '';
    return `<div class="au-trail-row">${escapeHtml(l.actor_name || '—')}・${formatDateTimeTW(l.ts)}・${action_label(l.action)}${suffix}</div>`;
  }).join('');
}
