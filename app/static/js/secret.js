const OP_MAP = { '×': '*', '÷': '/', '−': '-', 'x': '*' };

export function canonicalToken(key) {
  return OP_MAP[key] || key;
}

export function buildSequence(tokens) {
  return tokens.join('');
}

export async function sha256hex(str) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(str));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}

export async function matchesSecret(sequence, secretHash) {
  return (await sha256hex(sequence)) === secretHash;
}

export function withinWindow(loadTs, nowTs, windowMs = 6000) {
  return (nowTs - loadTs) <= windowMs;
}
