export async function loadRates() {
  try {
    const res = await fetch('/api/v1/fx');
    const data = await res.json();
    if (data.status !== 'ok') {
      return { ok: false, base: data.base, currencies: data.currencies || [] };
    }
    return {
      ok: true, base: data.base, currencies: data.currencies,
      rates: data.rates, fetchedAt: data.fetched_at,
    };
  } catch (err) {
    return { ok: false, base: 'USD', currencies: [] };
  }
}
