export function formatAmount(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return Number(n).toLocaleString('en-US');
}

export function lightLabel(light) {
  return { green: '🟢', yellow: '🟡', red: '🔴' }[light] || '⚪';
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
