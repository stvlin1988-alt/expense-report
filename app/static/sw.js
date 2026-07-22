/**
 * Service Worker — PWA 離線殼
 *   - /static/*：cache-first（計算機離線可用）
 *   - /auth/*、/face/*、/api/*：network-first 且「絕不快取」（認證/影像/匯率）
 *   - 導覽：network-first，離線 fallback 到快取
 * 所有分支保證回傳 Response（避免 respondWith(undefined) 例外）。
 */
// 靜態資產(js/css)變更時務必 bump 此版本號（如 calc-v2），
// 否則 cache-first 會讓客戶端持續使用舊檔（見下方 STATIC_URLS 的 cache-first 分支）。
const CACHE_NAME = 'calc-v69';
const STATIC_URLS = [
  '/',
  '/static/css/app.css',
  '/static/js/main.js',
  '/static/js/calculator.js',
  '/static/js/currency.js',
  '/static/js/secret.js',
  '/static/js/fx.js',
  '/static/js/camera.js',
  '/static/js/auth.js',
  '/static/js/expenses_util.js',
  '/static/js/expenses_api.js',
  '/static/js/admin_util.js',
  '/static/js/audit_util.js',
  '/static/js/capture.js',
  '/static/js/pending.js',
  '/static/js/employee_app.js',
  '/static/js/review.js',
  '/static/js/lightbox.js',
  '/static/js/wk_modal.js',
  '/static/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((c) => c.addAll(STATIC_URLS)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

async function networkFirst(request) {
  try {
    return await fetch(request);
  } catch (err) {
    const cached = await caches.match(request);
    return cached || Response.error();
  }
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 認證/影像/匯率：network-first，絕不快取
  if (url.pathname.startsWith('/auth/') ||
      url.pathname.startsWith('/face/') ||
      url.pathname.startsWith('/api/') ||
      url.pathname === '/expenses' ||
      url.pathname.startsWith('/expenses/')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // 靜態：cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((resp) => {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then((c) => c.put(event.request, clone));
          return resp;
        }).catch(() => Response.error());
      })
    );
    return;
  }

  // 導覽（含 '/'）：network-first
  event.respondWith(networkFirst(event.request));
});
