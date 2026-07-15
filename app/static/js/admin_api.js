async function req(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}

const withStore = (base, storeId) =>
  (storeId != null ? `${base}?store_id=${storeId}` : base);

export const api = {
  getUsers: (storeId) => req('GET', withStore('/admin/users', storeId)),
  getStores: () => req('GET', '/admin/stores'),
  getDevices: (storeId) => req('GET', withStore('/admin/devices', storeId)),
  createUser: (payload) => req('POST', '/admin/users', payload),
  resetPassword: (id, password) => req('POST', `/admin/users/${id}/password`, { password }),
  setActive: (id, active) => req('POST', `/admin/users/${id}/active`, { active }),
  setUserStore: (id, storeId) => req('POST', `/admin/users/${id}/store`, { store_id: storeId }),
  setUserRole: (id, role) => req('POST', `/admin/users/${id}/role`, { role }),
  enrollFace: (userId, faceImage) =>
    req('POST', '/face/enroll', { user_id: userId, face_image: faceImage }),
  createStore: (name, code) => req('POST', '/admin/stores', { name, code }),
  deleteStore: (id) => req('DELETE', `/admin/stores/${id}`),
  setStoreActive: (id, active) => req('POST', `/admin/stores/${id}/active`, { active }),
  approveDevice: (id, payload) => req('POST', `/admin/devices/${id}/approve`, payload),
  revokeDevice: (id) => req('POST', `/admin/devices/${id}/revoke`),
  changeMyPassword: (oldp, newp) =>
    req('POST', '/admin/me/password', { old_password: oldp, new_password: newp }),
  auditPending: (storeId) => req('GET', withStore('/audit/pending', storeId)),
  auditOverdue: (storeId) => req('GET', withStore('/audit/overdue', storeId)),
  auditEdit: (id, patch, storeId) => req('PATCH', withStore(`/audit/${id}`, storeId), patch),
  auditCheck: (id, storeId) => req('POST', withStore(`/audit/${id}/check`, storeId)),
  auditSummary: (storeId, before) => {
    const p = new URLSearchParams();
    if (storeId != null) p.set('store_id', storeId);
    if (before) p.set('before', before);
    const qs = p.toString();
    return req('GET', `/audit/summary${qs ? `?${qs}` : ''}`);
  },
  auditHandover: (type, storeId) => req('POST', '/audit/handover', { type, store_id: storeId }),
  auditUndo: (storeId) => req('POST', '/audit/handover/undo', { store_id: storeId }),
  auditHandoverItems: (hid, storeId) => req('GET', withStore(`/audit/handover/${hid}/items`, storeId)),
  auditOpenItems: (storeId) => req('GET', withStore('/audit/open-items', storeId)),
  auditDays: (storeId) => req('GET', withStore('/audit/days', storeId)),
  auditSummaryDates: (storeId) => req('GET', withStore('/audit/summary-dates', storeId)),
  expenseLogs: (id) => req('GET', `/expenses/${id}/logs`),
  auditByDate: (storeId, d) => {
    const p = new URLSearchParams();
    if (storeId != null) p.set('store_id', storeId);
    p.set('date', d);
    return req('GET', `/audit/by-date?${p.toString()}`);
  },
  auditLogs: (storeId, date, actorId) => {
    const p = new URLSearchParams();
    if (storeId != null) p.set('store_id', storeId);
    p.set('date', date);
    if (actorId != null) p.set('actor_id', actorId);
    return req('GET', `/audit/logs?${p.toString()}`);
  },
};
