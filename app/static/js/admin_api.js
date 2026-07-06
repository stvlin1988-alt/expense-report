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
  enrollFace: (userId, faceImage) =>
    req('POST', '/face/enroll', { user_id: userId, face_image: faceImage }),
  createStore: (name, code) => req('POST', '/admin/stores', { name, code }),
  approveDevice: (id, payload) => req('POST', `/admin/devices/${id}/approve`, payload),
  revokeDevice: (id) => req('POST', `/admin/devices/${id}/revoke`),
  changeMyPassword: (oldp, newp) =>
    req('POST', '/admin/me/password', { old_password: oldp, new_password: newp }),
};
