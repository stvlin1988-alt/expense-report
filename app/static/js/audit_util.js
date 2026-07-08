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
