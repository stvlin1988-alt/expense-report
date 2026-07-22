// 手機殼共用小工具（員工/主管手機殼共用）。原定義於 employee_app.js，抽出去重。
let toastTimer = null;
export function mbToast(msg) {
  const el = document.getElementById('mb-toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

// 切走 pane 前停止該 pane 容器內任何 live 相機串流（影像不落地）。
export function stopPaneCamera(container) {
  if (!container) return;
  container.querySelectorAll('video').forEach((v) => {
    if (v.srcObject) {
      v.srcObject.getTracks().forEach((t) => t.stop());
      v.srcObject = null;
    }
  });
}

export async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  return { status: res.status, data: await res.json().catch(() => ({})) };
}
