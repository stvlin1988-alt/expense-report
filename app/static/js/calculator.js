export class CalcEngine {
  constructor() { this._reset(); }

  _reset() {
    this.current = '0';
    this.stored = null;
    this.op = null;
    this.overwrite = true; // 下一個數字覆蓋顯示
  }

  clear() { this._reset(); }
  get display() { return this.current; }

  _num() { return parseFloat(this.current); }

  _set(n) {
    if (!isFinite(n)) { this.current = '錯誤'; return; }
    // 去除浮點雜訊：四捨五入到 10 位小數
    this.current = String(Math.round((n + Number.EPSILON) * 1e10) / 1e10);
  }

  inputDigit(d) {
    if (this.current === '錯誤') this._reset();
    if (this.overwrite) { this.current = d; this.overwrite = false; }
    else if (this.current === '0') this.current = d;
    else this.current += d;
  }

  inputDot() {
    if (this.current === '錯誤') this._reset();
    if (this.overwrite) { this.current = '0.'; this.overwrite = false; return; }
    if (!this.current.includes('.')) this.current += '.';
  }

  negate() {
    if (this.current === '0' || this.current === '錯誤') return;
    this.current = this.current.startsWith('-')
      ? this.current.slice(1) : '-' + this.current;
  }

  percent() {
    if (this.current === '錯誤') return;
    this._set(this._num() / 100);
    this.overwrite = true;
  }

  _apply(a, op, b) {
    switch (op) {
      case '+': return a + b;
      case '-': return a - b;
      case '*': return a * b;
      case '/': return b === 0 ? NaN : a / b;
      default: return b;
    }
  }

  inputOp(op) {
    if (this.current === '錯誤') return;
    if (this.op !== null && !this.overwrite) {
      this._set(this._apply(this.stored, this.op, this._num()));
      this.stored = this._num();
    } else {
      this.stored = this._num();
    }
    this.op = op;
    this.overwrite = true;
  }

  equals() {
    if (this.op === null || this.current === '錯誤') return;
    this._set(this._apply(this.stored, this.op, this._num()));
    this.op = null;
    this.stored = null;
    this.overwrite = true;
  }
}
