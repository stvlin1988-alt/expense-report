import test from 'node:test';
import assert from 'node:assert';
import { CalcEngine } from '../../app/static/js/calculator.js';

test('加法 2+3=5', () => {
  const c = new CalcEngine();
  c.inputDigit('2'); c.inputOp('+'); c.inputDigit('3'); c.equals();
  assert.equal(c.display, '5');
});

test('乘法 7*8=56', () => {
  const c = new CalcEngine();
  c.inputDigit('7'); c.inputOp('*'); c.inputDigit('8'); c.equals();
  assert.equal(c.display, '56');
});

test('前導 0：078 顯示 78，078*2=156', () => {
  const c = new CalcEngine();
  c.inputDigit('0'); c.inputDigit('7'); c.inputDigit('8');
  assert.equal(c.display, '78');
  c.inputOp('*'); c.inputDigit('2'); c.equals();
  assert.equal(c.display, '156');
});

test('連續運算 1+2+3=6', () => {
  const c = new CalcEngine();
  c.inputDigit('1'); c.inputOp('+'); c.inputDigit('2');
  c.inputOp('+'); c.inputDigit('3'); c.equals();
  assert.equal(c.display, '6');
});

test('除以 0 顯示 錯誤', () => {
  const c = new CalcEngine();
  c.inputDigit('5'); c.inputOp('/'); c.inputDigit('0'); c.equals();
  assert.equal(c.display, '錯誤');
});

test('percent：50% = 0.5', () => {
  const c = new CalcEngine();
  c.inputDigit('5'); c.inputDigit('0'); c.percent();
  assert.equal(c.display, '0.5');
});

test('negate 正負切換', () => {
  const c = new CalcEngine();
  c.inputDigit('9'); c.negate();
  assert.equal(c.display, '-9');
  c.negate();
  assert.equal(c.display, '9');
});

test('小數點 3.14', () => {
  const c = new CalcEngine();
  c.inputDigit('3'); c.inputDot(); c.inputDigit('1'); c.inputDigit('4');
  assert.equal(c.display, '3.14');
});

test('clear 歸零', () => {
  const c = new CalcEngine();
  c.inputDigit('9'); c.clear();
  assert.equal(c.display, '0');
});
