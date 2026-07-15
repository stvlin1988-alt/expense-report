export const periodsApi = {
  async getSettings() {
    const r = await fetch('/periods/settings');
    return { status: r.status, data: await r.json() };
  },
  async patchSettings(body) {
    const r = await fetch('/periods/settings', {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return { status: r.status, data: await r.json() };
  },
  // 農曆年提早結期（會計）：改某期 end_date
  async patchEndDate(pid, endDate) {
    const r = await fetch(`/periods/${pid}/end-date`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ end_date: endDate }),
    });
    return { status: r.status, data: await r.json() };
  },
};
