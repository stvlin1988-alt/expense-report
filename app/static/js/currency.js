// rates: {cur: 每 1 USD 對應的該幣金額}。跨幣：amount * rate[to] / rate[from]
export function cross(amount, from, to, rates) {
  const rf = rates[from], rt = rates[to];
  if (!rf || !rt) return null;
  return amount * (rt / rf);
}

export function convertAll(amount, from, currencies, rates) {
  const out = {};
  for (const c of currencies) {
    if (c === from) continue;
    const v = cross(amount, from, c, rates);
    if (v !== null) out[c] = v;
  }
  return out;
}
