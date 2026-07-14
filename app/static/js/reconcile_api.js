async function j(url, opts) {
  const r = await fetch(url, opts);
  let data = {};
  try { data = await r.json(); } catch (e) { /* 非 JSON：留空物件 */ }
  return { status: r.status, data };
}

export const rcApi = {
  pending: (q) => j('/reconcile/pending' + (q && Object.keys(q).length ? '?' + new URLSearchParams(q) : '')),
  approve: (id) => j(`/reconcile/${id}/approve`, { method: 'POST' }),
  approveBatch: (ids) => j('/reconcile/approve-batch', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  }),
  reject: (id, reason) => j(`/reconcile/${id}/reject`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  }),
  edit: (id, patch) => j(`/reconcile/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }),
  manual: (payload) => j('/reconcile/manual', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  // 注意：不是 /admin/stores —— 那支是 manager/super_admin 專用，會計會 403。
  stores: () => j('/reconcile/stores'),
  categories: () => j('/expenses/categories'),
};
