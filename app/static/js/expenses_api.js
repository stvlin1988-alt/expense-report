async function jsonFetch(url, opts) {
  const res = await fetch(url, opts);
  return { status: res.status, data: await res.json().catch(() => ({})) };
}
export const captureUpload = (image) => jsonFetch('/expenses', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ image }),
});
export const listPending = () => jsonFetch('/expenses/pending');
export const listCategories = () => jsonFetch('/expenses/categories');
export const patchExpense = (id, patch) => jsonFetch(`/expenses/${id}`, {
  method: 'PATCH', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(patch),
});
export const submitExpense = (id) => jsonFetch(`/expenses/${id}/submit`, { method: 'POST' });
export const reocrExpense = (id) => jsonFetch(`/expenses/${id}/reocr`, { method: 'POST' });
export const discardExpense = (id) => jsonFetch(`/expenses/${id}`, { method: 'DELETE' });
export const noReceipt = (payload) => jsonFetch('/expenses/no-receipt', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
});
export const getExpenseLogs = (id) => jsonFetch(`/expenses/${id}/logs`);
export const listSubmitted = () => jsonFetch('/expenses/submitted');
