import test from 'node:test';
import assert from 'node:assert';
import {
  isValidPin, roleLabel, filterByStore, deviceStatusLabel, sortPendingFirst, isOk,
} from '../../app/static/js/admin_util.js';

test('isValidPin 僅接受 4 位純數字', () => {
  assert.equal(isValidPin('1234'), true);
  assert.equal(isValidPin('12a4'), false);
  assert.equal(isValidPin('123'), false);
  assert.equal(isValidPin('12345'), false);
  assert.equal(isValidPin(1234), false);
});

test('roleLabel 對映中文、未知原樣', () => {
  assert.equal(roleLabel('super_admin'), '業主');
  assert.equal(roleLabel('manager'), '店長');
  assert.equal(roleLabel('employee'), '員工');
  assert.equal(roleLabel('accountant'), '會計');
  assert.equal(roleLabel('weird'), 'weird');
});

test('filterByStore：null 回全部、否則依 store_id', () => {
  const items = [{ store_id: 1 }, { store_id: 2 }, { store_id: null }];
  assert.equal(filterByStore(items, null).length, 3);
  assert.deepEqual(filterByStore(items, 2), [{ store_id: 2 }]);
  // 不 mutate 原陣列
  assert.equal(items.length, 3);
});

test('deviceStatusLabel：撤銷優先於核准', () => {
  assert.equal(deviceStatusLabel({ is_revoked: true, is_approved: true }), '已撤銷');
  assert.equal(deviceStatusLabel({ is_revoked: false, is_approved: true }), '已核准');
  assert.equal(deviceStatusLabel({ is_revoked: false, is_approved: false }), '待核准');
});

test('sortPendingFirst：待核准排最前，不 mutate', () => {
  const devs = [
    { id: 1, is_approved: true, is_revoked: false },
    { id: 2, is_approved: false, is_revoked: false },
    { id: 3, is_approved: true, is_revoked: true },
  ];
  const out = sortPendingFirst(devs);
  assert.equal(out[0].id, 2);
  assert.equal(devs[0].id, 1); // 原陣列不變
});

test('isOk：200 + status ok', () => {
  assert.equal(isOk(200, { status: 'ok' }), true);
  assert.equal(isOk(200, { status: 'error' }), false);
  assert.equal(isOk(403, { status: 'ok' }), false);
  assert.equal(isOk(200, null), false);
});
