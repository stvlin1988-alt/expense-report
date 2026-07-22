// 主管稽核 pane（UI 重塑 2026-07）：Task 1 先建 stub 讓 manager_app.js 殼可獨立驗收。
// Task 2/3 補上待稽核/總表子分頁、稽核卡、action bar 交班/結班/取消邏輯。
export function renderAuditPane(container) {
  container.innerHTML = '<div class="mb-ph-card"><h3>稽核（待實作）</h3></div>';
}

export function wireActionBar() {}
