export function formatAmount(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return Number(n).toLocaleString('en-US');
}

export function lightLabel(light) {
  return { green: '🟢', yellow: '🟡', red: '🔴' }[light] || '⚪';
}

// 解析使用者輸入的金額字串（去千分位逗號/空白/前置 NT$、$）。
// 回傳 { value, valid }；空字串或無法解析成有限數 → { value: null, valid: false }。
export function parseAmountInput(raw) {
  const s = String(raw == null ? '' : raw)
    .trim()
    .replace(/^NT\$/i, '')
    .replace(/^\$/, '')
    .replace(/,/g, '')
    .replace(/\s/g, '');
  if (s === '') return { value: null, valid: false };
  const n = Number(s);
  if (!Number.isFinite(n)) return { value: null, valid: false };
  return { value: n, valid: true };
}

export function businessDateDisplay(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(d);
  const get = (t) => parts.find((p) => p.type === t).value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}
