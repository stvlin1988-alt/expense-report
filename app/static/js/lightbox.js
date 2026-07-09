// 原圖放大檢視：右上 × 關閉、雙指 pinch 縮放、拖曳平移、桌機滾輪縮放、點背景/Esc 關閉。
// 員工確認區與主管稽核共用。
export function openImageLightbox(url) {
  if (!url) return;
  const ov = document.createElement('div');
  ov.className = 'au-lightbox';

  const stage = document.createElement('div');
  stage.className = 'au-lightbox-stage';
  const img = document.createElement('img');
  img.src = url; img.alt = '原單'; img.draggable = false;
  stage.appendChild(img);

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'au-lightbox-close';
  closeBtn.setAttribute('aria-label', '關閉');
  closeBtn.textContent = '×';

  ov.appendChild(stage);
  ov.appendChild(closeBtn);

  // 縮放/平移狀態
  let scale = 1, tx = 0, ty = 0;
  const MIN = 1, MAX = 5;
  const apply = () => { img.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`; };
  const clamp = (s) => Math.min(MAX, Math.max(MIN, s));

  function onMouseMove(ev) {
    if (!dragging) return;
    tx = dragTx + (ev.clientX - dragX); ty = dragTy + (ev.clientY - dragY); apply();
  }
  function onMouseUp() { dragging = false; }
  const onKey = (ev) => { if (ev.key === 'Escape') close(); };
  const close = () => {
    ov.remove();
    document.removeEventListener('keydown', onKey);
    window.removeEventListener('mousemove', onMouseMove);
    window.removeEventListener('mouseup', onMouseUp);
  };

  closeBtn.addEventListener('click', (ev) => { ev.stopPropagation(); close(); });
  ov.addEventListener('click', (ev) => { if (ev.target === ov) close(); }); // 只點背景才關

  // 雙指 pinch 縮放 + 單指拖曳平移
  let mode = null, startDist = 0, startScale = 1;
  let startX = 0, startY = 0, startTx = 0, startTy = 0;
  const dist = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
  stage.addEventListener('touchstart', (ev) => {
    if (ev.touches.length === 2) {
      mode = 'pinch'; startDist = dist(ev.touches); startScale = scale; ev.preventDefault();
    } else if (ev.touches.length === 1 && scale > 1) {
      mode = 'pan';
      startX = ev.touches[0].clientX; startY = ev.touches[0].clientY;
      startTx = tx; startTy = ty; ev.preventDefault();
    }
  }, { passive: false });
  stage.addEventListener('touchmove', (ev) => {
    if (mode === 'pinch' && ev.touches.length === 2) {
      scale = clamp(startScale * (dist(ev.touches) / startDist));
      if (scale === 1) { tx = 0; ty = 0; }
      apply(); ev.preventDefault();
    } else if (mode === 'pan' && ev.touches.length === 1) {
      tx = startTx + (ev.touches[0].clientX - startX);
      ty = startTy + (ev.touches[0].clientY - startY);
      apply(); ev.preventDefault();
    }
  }, { passive: false });
  stage.addEventListener('touchend', (ev) => { if (ev.touches.length === 0) mode = null; });

  // 桌機：滾輪縮放 + 拖曳平移（方便本機/VM 測）
  stage.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    scale = clamp(scale * (ev.deltaY < 0 ? 1.15 : 1 / 1.15));
    if (scale === 1) { tx = 0; ty = 0; }
    apply();
  }, { passive: false });
  let dragging = false, dragX = 0, dragY = 0, dragTx = 0, dragTy = 0;
  stage.addEventListener('mousedown', (ev) => {
    if (scale <= 1) return;
    dragging = true; dragX = ev.clientX; dragY = ev.clientY; dragTx = tx; dragTy = ty;
    ev.preventDefault();
  });
  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
  document.addEventListener('keydown', onKey);
  document.body.appendChild(ov);
}
