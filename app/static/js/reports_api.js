export const reportsApi = {
  async monthly(periodId) {
    const q = periodId ? `?period_id=${periodId}` : '';
    const r = await fetch(`/reports/monthly${q}`);
    return { status: r.status, data: await r.json() };
  },
};
