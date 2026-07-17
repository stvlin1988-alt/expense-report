// 共用 app modal（取代 window.prompt / window.confirm）
// 自建 backdrop DOM append 到 document.body，Promise 化。與 index.html 現有的
// #modal-root（面板/大表單掛載點）無關，故不需改 index.html。
import { escapeHtml } from './admin_util.js';

/**
 * wkConfirm({ title, desc, okLabel='確定', danger=false }) => Promise<boolean>
 * 取消（按取消/X/背景/Esc）resolve(false)；按確認 resolve(true)。
 */
export function wkConfirm({ title, desc = '', okLabel = '確定', danger = false } = {}) {
  return new Promise((resolve) => {
    const bd = document.createElement('div');
    bd.className = 'wk-modal-backdrop open';
    bd.innerHTML = `<div class="wk-modal" role="dialog" aria-modal="true">
      <div class="wk-modal-head"><div class="wk-modal-title">${escapeHtml(title)}</div>
        <button class="wk-modal-x" type="button" aria-label="關閉">×</button></div>
      <div class="wk-modal-body">${escapeHtml(desc)}</div>
      <div class="wk-modal-foot">
        <button class="wk-btn wk-btn-secondary" data-no type="button">取消</button>
        <button class="wk-btn ${danger ? 'wk-btn-danger' : 'wk-btn-primary'}" data-yes type="button">${escapeHtml(okLabel)}</button>
      </div></div>`;
    const done = (v) => { bd.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') done(false); };
    bd.querySelector('[data-yes]').addEventListener('click', () => done(true));
    bd.querySelector('[data-no]').addEventListener('click', () => done(false));
    bd.querySelector('.wk-modal-x').addEventListener('click', () => done(false));
    bd.addEventListener('click', (e) => { if (e.target === bd) done(false); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(bd);
    bd.querySelector('[data-yes]').focus();
  });
}

/**
 * wkPrompt({ title, desc, okLabel='送出', placeholder='', validate }) => Promise<string|null>
 * 取消（按取消/X/背景/Esc）resolve(null)——與原生 window.prompt 取消語意一致。
 * validate(value) 若回傳非空字串，視為錯誤訊息：顯示在 .wk-modal-err、不關閉 modal。
 */
export function wkPrompt({ title, desc = '', okLabel = '送出', placeholder = '', validate } = {}) {
  return new Promise((resolve) => {
    const bd = document.createElement('div');
    bd.className = 'wk-modal-backdrop open';
    bd.innerHTML = `<div class="wk-modal" role="dialog" aria-modal="true">
      <div class="wk-modal-head"><div class="wk-modal-title">${escapeHtml(title)}</div>
        <button class="wk-modal-x" type="button" aria-label="關閉">×</button></div>
      <div class="wk-modal-body">${escapeHtml(desc)}
        <input class="wk-input" type="text" placeholder="${escapeHtml(placeholder)}">
        <div class="wk-modal-err"></div>
      </div>
      <div class="wk-modal-foot">
        <button class="wk-btn wk-btn-secondary" data-no type="button">取消</button>
        <button class="wk-btn wk-btn-primary" data-yes type="button">${escapeHtml(okLabel)}</button>
      </div></div>`;
    const input = bd.querySelector('.wk-input');
    const errEl = bd.querySelector('.wk-modal-err');
    const done = (v) => { bd.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
    const submit = () => {
      const v = input.value;
      if (typeof validate === 'function') {
        const msg = validate(v);
        if (msg) { errEl.textContent = msg; return; }
      }
      done(v);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') done(null);
      else if (e.key === 'Enter') { e.preventDefault(); submit(); }
    };
    bd.querySelector('[data-yes]').addEventListener('click', submit);
    bd.querySelector('[data-no]').addEventListener('click', () => done(null));
    bd.querySelector('.wk-modal-x').addEventListener('click', () => done(null));
    bd.addEventListener('click', (e) => { if (e.target === bd) done(null); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(bd);
    input.focus();
  });
}
