export function isValidPin(pw) {
  return typeof pw === 'string' && /^\d{4}$/.test(pw);
}

export const ROLE_LABEL = {
  employee: '員工', manager: '主管', accountant: '會計', super_admin: '經理',
};

export function roleLabel(role) {
  return ROLE_LABEL[role] || role;
}

export function filterByStore(items, storeId) {
  if (storeId == null) return items.slice();
  return items.filter((it) => it.store_id === storeId);
}

export function deviceStatusLabel(d) {
  if (d.is_revoked) return '已撤銷';
  if (d.is_approved) return '已核准';
  return '待核准';
}

export function sortPendingFirst(devices) {
  const rank = (d) => ((!d.is_approved && !d.is_revoked) ? 0 : 1);
  return devices.slice().sort((a, b) => rank(a) - rank(b));
}

export function isOk(httpStatus, body) {
  return httpStatus === 200 && !!body && body.status === 'ok';
}

export function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
