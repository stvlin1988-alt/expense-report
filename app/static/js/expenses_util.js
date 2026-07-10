export function formatAmount(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return Number(n).toLocaleString('en-US');
}

export function lightLabel(light) {
  return { green: '🟢', yellow: '🟡', red: '🔴' }[light] || '⚪';
}

// 加總金額（複查區總額）。用「分」為單位加總避免浮點誤差；忽略非有限數的 amount。
export function sumAmounts(expenses) {
  const cents = (expenses || []).reduce((acc, e) => {
    const a = e && e.amount;
    return typeof a === 'number' && Number.isFinite(a) ? acc + Math.round(a * 100) : acc;
  }, 0);
  return cents / 100;
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

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// 分類樹 → <optgroup>/<option> 字串（純函式，不依賴 DOM）。
// 首列固定「未分類」空值 option；selectedId 對應的 option 加 selected。
export function categoryOptionsHtml(tree, selectedId) {
  let html = '<option value="">未分類</option>';
  (tree || []).forEach((grp) => {
    const items = grp.items || [];
    if (items.length === 0) {
      // 無子類的大類（如「特支」）→ 直接當可選 option（大類 id）；粗體對齊 optgroup 標題
      const sel = String(grp.id) === String(selectedId) ? ' selected' : '';
      html += `<option value="${grp.id}" style="font-weight:bold"${sel}>${esc(grp.name)}</option>`;
      return;
    }
    html += `<optgroup label="${esc(grp.name)}">`;
    items.forEach((it) => {
      const sel = String(it.id) === String(selectedId) ? ' selected' : '';
      html += `<option value="${it.id}"${sel}>${esc(it.name)}</option>`;
    });
    html += '</optgroup>';
  });
  return html;
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
