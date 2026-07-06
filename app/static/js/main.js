import { CalcEngine } from './calculator.js';
import { convertAll } from './currency.js';
import { loadRates } from './fx.js';
import { canonicalToken, buildSequence, matchesSecret, withinWindow } from './secret.js';
import { openAuth, showAppView } from './auth.js';
import { showAdminPanel } from './admin.js';

const cfg = JSON.parse(document.getElementById('app-config').textContent);
const engine = new CalcEngine();
const fxPanel = document.getElementById('fx-panel');
const calcDisplay = document.getElementById('calc-display');

let mode = 'calc';           // 'calc' | 'fx'
let seq = [];                // 暗號 token 累積（自載入/清除起）
let triggerLocked = false;   // 6 秒窗逾時後鎖定
const loadTs = Date.now();
setTimeout(() => {
  triggerLocked = true;
  cfg.secretHash = null;
  cfg.identity = null;
  const acEl = document.getElementById('app-config');
  if (acEl) acEl.textContent = '{}';
}, 6000);

// ---- 顯示 ----
function renderCalc() { calcDisplay.textContent = engine.display; }

// ---- 匯率 ----
let fxState = { ok: false, currencies: [], rates: {}, from: 'TWD', amount: '0' };

function renderFx() {
  const chips = document.getElementById('fx-currencies');
  const amountEl = document.getElementById('fx-amount');
  const results = document.getElementById('fx-results');
  const updated = document.getElementById('fx-updated');

  chips.innerHTML = '';
  fxState.currencies.forEach((c) => {
    const b = document.createElement('button');
    b.className = 'fx-chip' + (c === fxState.from ? ' active' : '');
    b.textContent = c;
    b.type = 'button';
    b.addEventListener('click', () => { fxState.from = c; renderFx(); });
    chips.appendChild(b);
  });

  amountEl.textContent = fxState.amount;

  if (!fxState.ok) {
    results.innerHTML = '<div class="fx-unavailable">暫時無法取得匯率</div>';
    updated.textContent = '';
    return;
  }
  const out = convertAll(parseFloat(fxState.amount) || 0, fxState.from,
    fxState.currencies, fxState.rates);
  results.innerHTML = '';
  Object.keys(out).forEach((c) => {
    const row = document.createElement('div');
    row.className = 'fx-row';
    row.innerHTML = `<span>${c}</span><span>${out[c].toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>`;
    results.appendChild(row);
  });
  updated.textContent = fxState.fetchedAt
    ? '更新：' + new Date(fxState.fetchedAt).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei' })
    : '';
}

async function initFx() {
  const r = await loadRates();
  fxState.ok = r.ok;
  fxState.currencies = r.currencies || [];
  fxState.rates = r.rates || {};
  if (fxState.currencies.length && !fxState.currencies.includes(fxState.from)) {
    fxState.from = fxState.currencies[0];
  }
  fxState.fetchedAt = r.fetchedAt;
  if (mode === 'fx') renderFx();
}

// ---- tab 切換 ----
document.querySelectorAll('.tab').forEach((t) => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
    t.classList.add('active');
    mode = t.dataset.tab;
    if (mode === 'fx') {
      calcDisplay.hidden = true; fxPanel.hidden = false; renderFx();
    } else {
      calcDisplay.hidden = false; fxPanel.hidden = true; renderCalc();
    }
  });
});

// ---- fx 金額輸入 ----
function fxDigit(d) {
  if (fxState.amount === '0') fxState.amount = d;
  else fxState.amount += d;
  renderFx();
}
function fxDot() { if (!fxState.amount.includes('.')) fxState.amount += '.'; renderFx(); }
function fxClear() { fxState.amount = '0'; renderFx(); }

// ---- 暗號偵測（僅 calc mode）----
async function checkSecret() {
  if (!cfg.secretHash) return false;
  if (triggerLocked || mode !== 'calc') return false;
  if (!withinWindow(loadTs, Date.now())) { triggerLocked = true; return false; }
  const ok = await matchesSecret(buildSequence(seq), cfg.secretHash);
  return ok;
}

// ---- 鍵盤事件 ----
document.querySelector('.keys').addEventListener('click', async (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;

  const digit = btn.dataset.digit;
  const op = btn.dataset.op;
  const action = btn.dataset.action;

  if (mode === 'fx') {
    if (digit !== undefined) fxDigit(digit);
    else if (action === 'dot') fxDot();
    else if (action === 'clear') fxClear();
    // 匯率 tab 忽略運算子與 =
    return;
  }

  // calc mode：同時餵計算機引擎與暗號序列
  if (digit !== undefined) { seq.push(digit); engine.inputDigit(digit); renderCalc(); }
  else if (op !== undefined) { seq.push(canonicalToken(btn.textContent)); engine.inputOp(op); renderCalc(); }
  else if (action === 'dot') { seq.push('.'); engine.inputDot(); renderCalc(); }
  else if (action === 'negate') { engine.negate(); renderCalc(); }
  else if (action === 'percent') { engine.percent(); renderCalc(); }
  else if (action === 'clear') { seq = []; engine.clear(); renderCalc(); }
  else if (action === 'equals') {
    if (await checkSecret()) {
      seq = []; engine.clear(); renderCalc();
      window.__openAuth(cfg.seedMode);   // Task 11 換成真流程
      return;
    }
    seq = []; engine.equals(); renderCalc();
  }
});

window.__openAuth = openAuth;

// 若伺服器判定本 session 已登入 → 暗號直接回登入後畫面（不需重打密碼）
// （由 Task 11：登入後畫面）。這裡僅在暗號觸發時判斷，故保留 identity 供 openAuth 分流。
if (cfg.identity) {
  const orig = window.__openAuth;
  window.__openAuth = function (seedMode) {
    if (cfg.identity) {
      if (cfg.identity.role === 'manager' || cfg.identity.role === 'super_admin') {
        showAdminPanel(cfg.identity);
      } else {
        showAppView(cfg.identity);
      }
      return;
    }
    orig(seedMode);
  };
}

initFx();
renderCalc();
