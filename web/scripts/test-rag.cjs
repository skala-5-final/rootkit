/* eslint-disable @typescript-eslint/no-require-imports */
// Run with: node --test scripts/test-rag.cjs
// Uses the production TS modules and real JWT signing; only HTTP/model responses are fixtures.
const { test, beforeEach, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const modules = new Map();
function load(relative) {
  const file = path.resolve(root, relative);
  if (modules.has(file)) return modules.get(file).exports;
  const mod = new Module(file, module);
  mod.filename = file;
  mod.paths = Module._nodeModulePaths(path.dirname(file));
  const nativeRequire = mod.require.bind(mod);
  mod.require = name => {
    if (name === 'server-only') return {}; // The boundary is enforced by next build, not Node's test loader.
    if (name.startsWith('@/') || name.startsWith('.')) {
      const target = name.startsWith('@/') ? path.join(root, 'src', name.slice(2)) : path.resolve(path.dirname(file), name);
      for (const suffix of ['', '.ts', '.tsx']) if (fs.existsSync(target + suffix) && fs.statSync(target + suffix).isFile()) return load(target + suffix);
    }
    return nativeRequire(name);
  };
  modules.set(file, mod);
  mod._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, file);
  return mod.exports;
}

const contract = load('src/lib/rag-contract.ts');
const client = load('src/lib/rag-client.ts');
const browser = load('src/lib/rag-browser.ts');
const session = load('src/lib/session.ts');
const attempts = load('src/app/api/rag/attempts/route.ts');
const attempt = load('src/app/api/rag/attempts/[id]/route.ts');
const evaluations = load('src/app/api/rag/evaluations/route.ts');
const history = load('src/app/api/rag/history/route.ts');
const realFetch = global.fetch;
const originalEnv = { ...process.env };
let calls;
const exercise = {
  id: 'dataset-a-exercise', version: 1, dataset_id: 'dataset-a', dataset_version: 1,
  stage: 1, language: 'ko', recipient_group: 'general', title: '자료 요청', scenario: '11월 3일까지 자료를 요청하세요.',
  requirements: ['기한과 요청 자료를 명시하세요.'], facts: [{ id: 'deadline', value: '11월 3일', kind: 'date', origin: 'exercise', source_ids: [] }],
  original: '자료 보내 주세요.', subject: '자료 요청', recipient: '개발팀', source_ids: ['mail-a'],
};
const displayed = { attempt_id: 'attempt-a', exercise };
const answer = { subject: '자료 요청', body: '11월 3일까지 자료 부탁드립니다.' };
const result = { attempt_id: 'attempt-a', request_id: 'request-a', total: null, status: 'match', summary: '요구사항을 충족했습니다.', feedback: [] };

beforeEach(() => {
  process.env.JWT_SECRET = 'test-only-jwt-secret-at-least-thirty-two-characters';
  process.env.AI_API_BASE_URL = 'http://ai.test/api/v1';
  process.env.AI_API_TOKEN = 'test-only-internal-token';
  calls = [];
  global.fetch = async (...args) => { calls.push(args); throw new Error('Unexpected HTTP request'); };
});
after(() => { global.fetch = realFetch; for (const key of ['JWT_SECRET', 'AI_API_BASE_URL', 'AI_API_TOKEN']) { if (originalEnv[key] === undefined) delete process.env[key]; else process.env[key] = originalEnv[key]; } });
function reply(body, status = 200) {
  global.fetch = async (...args) => { calls.push(args); return Response.json(body, { status }); };
}
async function request(url, body, options = {}) {
  const token = options.token === undefined ? await session.signSession({ userId: 'real-user', loginId: 'rookie', name: '루키' }) : options.token;
  const req = new Request(`${options.baseUrl || 'http://localhost:3000'}${url}`, { method: body === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  req.cookies = { get: name => name === session.sessionCookie && token ? { value: token } : undefined };
  return req;
}

test('learner DTO removes internal criteria, approvals and nested review information', () => {
  const parsed = contract.parseRagAttempt({ ...displayed, criteria_snapshot: { secret: true }, exercise: { ...exercise, criteria: ['hidden'], review_status: 'passed', facts: [{ ...exercise.facts[0], review_reason: 'hidden' }] } });
  assert.deepEqual(parsed, displayed);
  assert.equal(JSON.stringify(parsed).includes('hidden'), false);
});
test('rejects scored, malformed and unreviewable response shapes', () => {
  for (const bad of [{ ...result, total: 100 }, { ...result, status: 'passed' }, { ...result, feedback: [{}] }]) assert.throws(() => contract.parseRagEvaluation(bad));
  for (const bad of [{ ...exercise, original: null }, { ...exercise, dataset_version: 0 }, { ...exercise, recipient_group: 'guessed' }, { ...exercise, source_ids: [] }]) assert.throws(() => contract.parseRagExercise(bad));
});
test('all RAG routes require verified JWT even without proxy', async () => {
  const responses = await Promise.all([
    attempts.POST(await request('/api/rag/attempts', { stage: 1 }, { token: '' })),
    evaluations.POST(await request('/api/rag/evaluations', {}, { token: 'forged' })),
    attempt.GET(await request('/api/rag/attempts/attempt-a', undefined, { token: '' }), { params: Promise.resolve({ id: 'attempt-a' }) }),
    history.GET(await request('/api/rag/history', undefined, { token: '' })),
  ]);
  assert.deepEqual(responses.map(response => response.status), [401, 401, 401, 401]);
  assert.equal(calls.length, 0);
});
test('rejects browser-provided user, criteria and review fields', async () => {
  for (const extra of [{ user_id: 'victim' }, { criteria: [] }, { review_status: 'passed' }]) {
    const response = await attempts.POST(await request('/api/rag/attempts', { stage: 1, ...extra }));
    assert.equal(response.status, 422);
  }
  assert.equal(calls.length, 0);
});
test('rejects cross-site mutations before contacting AI', async () => {
  const response = await attempts.POST(await request('/api/rag/attempts', { stage: 1 }, { headers: { origin: 'https://attacker.test' } }));
  assert.equal(response.status, 403);
  assert.equal(calls.length, 0);
});
test('same-origin browser Host is accepted when Next normalizes URL to localhost', async () => {
  reply(displayed);
  const response = await attempts.POST(await request('/api/rag/attempts', { stage: 1 }, {
    baseUrl: 'http://localhost:3001', headers: { host: '127.0.0.1:3001', origin: 'http://127.0.0.1:3001', 'sec-fetch-site': 'same-origin' },
  }));
  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
});
test('public Host without a port does not inherit the internal Next port', async () => {
  reply(displayed);
  const response = await attempts.POST(await request('/api/rag/attempts', { stage: 1 }, {
    baseUrl: 'http://localhost:3001', headers: { host: 'rootkit.test', origin: 'http://rootkit.test' },
  }));
  assert.equal(response.status, 200);
});
test('Host comparison rejects malicious Origin and ignores spoofed forwarded host', async () => {
  const response = await attempts.POST(await request('/api/rag/attempts', { stage: 1 }, {
    baseUrl: 'http://localhost:3001', headers: { host: '127.0.0.1:3001', origin: 'http://attacker.test:3001', 'x-forwarded-host': 'attacker.test:3001' },
  }));
  assert.equal(response.status, 403);
  assert.equal(calls.length, 0);
});
test('display request creates server attempt with JWT identity and strips internal fields', async () => {
  reply({ ...displayed, exercise: { ...exercise, criteria: ['private'] } });
  const response = await attempts.POST(await request('/api/rag/attempts', { stage: 1 }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), displayed);
  assert.equal(response.headers.get('cache-control'), 'private, no-store');
  assert.deepEqual(JSON.parse(calls[0][1].body), { user_id: 'real-user', stage: 1 });
  assert.equal(calls[0][1].headers.Authorization, 'Bearer test-only-internal-token');
  assert.equal(calls[0][1].redirect, 'error');
});
test('resume and resubmit old attempt without looking in active problem catalog', async () => {
  reply(displayed);
  const response = await attempt.GET(await request('/api/rag/attempts/attempt-a?user_id=victim'), { params: Promise.resolve({ id: 'attempt-a' }) });
  assert.equal(response.status, 200);
  assert.equal(calls[0][0].pathname, '/api/v1/attempts/attempt-a');
  assert.equal(calls[0][0].searchParams.get('user_id'), 'real-user');
  reply(result);
  const evaluated = await evaluations.POST(await request('/api/rag/evaluations', { attempt_id: 'attempt-a', request_id: 'request-a', answer: { ...answer, criteria: ['ignored'] } }));
  assert.equal(evaluated.status, 200);
  assert.deepEqual(JSON.parse(calls[1][1].body), { user_id: 'real-user', attempt_id: 'attempt-a', request_id: 'request-a', answer });
});
test('same answer retry retains request ID; edited answer receives a new ID', () => {
  const first = contract.requestForAnswer(null, answer, () => 'first');
  assert.equal(contract.requestForAnswer(first, { ...answer }, () => 'should-not-run'), first);
  assert.equal(contract.requestForAnswer(first, { ...answer, body: `${answer.body} 감사합니다.` }, () => 'second').request_id, 'second');
});
test('browser draft and pending request survive reload with user/attempt separation', () => {
  const saved = new Map();
  global.localStorage = { getItem: key => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value) };
  try {
    const draft = { answer, pending: { request_id: 'request-a', answer } };
    assert.equal(browser.saveRagDraft('real-user', 'attempt-a', draft), true);
    assert.deepEqual(browser.readRagDraft('real-user', 'attempt-a'), draft);
    assert.equal(browser.readRagDraft('another-user', 'attempt-a').pending, null);
  } finally { delete global.localStorage; }
});
test('confirmed evaluations allow a fresh evaluation of the same answer, including withheld feedback', async () => {
  for (const status of ['match', 'needs_revision', 'insufficient_evidence']) {
    let draft = { answer: { ...answer }, pending: null };
    const sent = [];
    global.fetch = async (_url, options) => {
      const body = JSON.parse(options.body);
      sent.push(body);
      return Response.json({ ...result, request_id: body.request_id, status });
    };
    const persist = next => { draft = next; };
    const first = await browser.evaluateRagDraft('attempt-a', draft, persist);
    assert.equal(first.status, status);
    assert.deepEqual(draft, { answer, pending: null });
    await browser.evaluateRagDraft('attempt-a', draft, persist);
    assert.notEqual(sent[0].request_id, sent[1].request_id);
    assert.deepEqual(sent[0].answer, sent[1].answer);
    assert.deepEqual(draft, { answer, pending: null });
  }
});
test('timeout retains the pending request across reload, then a confirmed retry clears it', async () => {
  const saved = new Map();
  global.localStorage = { getItem: key => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value) };
  try {
    let draft = { answer: { ...answer }, pending: null };
    const persist = next => { draft = next; browser.saveRagDraft('real-user', 'attempt-a', next); };
    let timedOutId;
    global.fetch = async (_url, options) => {
      timedOutId = JSON.parse(options.body).request_id;
      throw new DOMException('timeout', 'TimeoutError');
    };
    await assert.rejects(() => browser.evaluateRagDraft('attempt-a', draft, persist), error => error.name === 'TimeoutError');
    draft = browser.readRagDraft('real-user', 'attempt-a');
    assert.equal(draft.pending.request_id, timedOutId);
    assert.deepEqual(draft.answer, answer);
    global.fetch = async (_url, options) => {
      const body = JSON.parse(options.body);
      assert.equal(body.request_id, timedOutId);
      return Response.json({ ...result, request_id: body.request_id });
    };
    await browser.evaluateRagDraft('attempt-a', draft, persist);
    assert.deepEqual(browser.readRagDraft('real-user', 'attempt-a'), { answer, pending: null });
    assert.match(browser.ragError(new DOMException('timeout', 'TimeoutError')), /이전 평가 결과 확인하기/);
  } finally { delete global.localStorage; }
});
test('legacy pending requests recover their cached result once and allow a new evaluation', async () => {
  let draft = { answer: { ...answer }, pending: { request_id: 'legacy-completed-request', answer: { ...answer } } };
  const sent = [];
  global.fetch = async (_url, options) => {
    const body = JSON.parse(options.body);
    sent.push(body);
    return Response.json({ ...result, request_id: body.request_id, status: 'insufficient_evidence' });
  };
  const persist = next => { draft = next; };
  await browser.evaluateRagDraft('attempt-a', draft, persist);
  assert.equal(sent[0].request_id, 'legacy-completed-request');
  assert.deepEqual(draft, { answer, pending: null });
  await browser.evaluateRagDraft('attempt-a', draft, persist);
  assert.notEqual(sent[1].request_id, 'legacy-completed-request');
});
test('network failures and mismatched responses retain the answer and pending request for recovery', async () => {
  let draft = { answer: { ...answer }, pending: null };
  const persist = next => { draft = next; };
  global.fetch = async () => { throw new TypeError('network disconnected'); };
  await assert.rejects(() => browser.evaluateRagDraft('attempt-a', draft, persist), /network disconnected/);
  const requestId = draft.pending.request_id;
  reply({ ...result, request_id: 'another-request' });
  await assert.rejects(() => browser.evaluateRagDraft('attempt-a', draft, persist), /평가 결과가 요청과 일치하지 않습니다/);
  assert.equal(draft.pending.request_id, requestId);
  assert.deepEqual(draft.answer, answer);
});
test('ownership rejection is preserved and no response data is exposed', async () => {
  reply({ error: 'private details', code: 'not_found' }, 404);
  const response = await attempt.GET(await request('/api/rag/attempts/other-attempt'), { params: Promise.resolve({ id: 'other-attempt' }) });
  assert.equal(response.status, 404);
  assert.equal((await response.text()).includes('private details'), false);
});
test('request conflicts stay conflicts and user can retry without changing server ID', async () => {
  reply({ error: 'conflict', code: 'request_conflict' }, 409);
  const response = await evaluations.POST(await request('/api/rag/evaluations', { attempt_id: 'attempt-a', request_id: 'request-a', answer }));
  assert.equal(response.status, 409);
  assert.equal((await response.json()).code, 'request_conflict');
});
test('missing config and empty catalogs never produce demo success', async () => {
  delete process.env.AI_API_TOKEN;
  let response = await attempts.POST(await request('/api/rag/attempts', { stage: 1 }));
  assert.equal(response.status, 503);
  assert.equal(calls.length, 0);
  process.env.AI_API_TOKEN = 'test-token';
  reply({ error: 'No catalog', code: 'no_active_catalog' }, 503);
  response = await attempts.POST(await request('/api/rag/attempts', { stage: 1 }));
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, 'no_active_catalog');
});
test('upstream malformed JSON, ID mismatch and timeout are explicit failures', async () => {
  global.fetch = async () => new Response('not-json');
  await assert.rejects(() => client.createRagAttempt('real-user', 1), error => error.code === 'invalid_response');
  reply({ ...result, request_id: 'wrong-request' });
  await assert.rejects(() => client.evaluateRag('real-user', 'attempt-a', 'request-a', answer), error => error.code === 'invalid_response');
  global.fetch = async () => { throw new DOMException('timeout', 'TimeoutError'); };
  await assert.rejects(() => client.evaluateRag('real-user', 'attempt-a', 'request-a', answer), error => error.status === 504);
});
test('history is server-owned and cross-linked mismatches are rejected', async () => {
  const item = { ...displayed, submissions: [{ request_id: 'request-a', answer, result, created_at: '2026-10-23T01:00:00Z' }] };
  reply({ items: [item], user_id: 'ignored' });
  const response = await history.GET(await request('/api/rag/history?user_id=victim'));
  assert.equal(response.status, 200);
  assert.equal(calls[0][0].searchParams.get('user_id'), 'real-user');
  assert.deepEqual(await response.json(), { items: [item] });
  assert.throws(() => contract.parseRagHistory({ items: [{ ...item, submissions: [{ ...item.submissions[0], request_id: 'wrong' }] }] }));
});
test('STEP 0 demo evaluation remains available without model configuration', async () => {
  delete process.env.AI_API_TOKEN;
  const demo = load('src/app/api/demo/evaluations/route.ts');
  const response = await demo.POST(await request('/api/demo/evaluations', { exerciseId: 'b-sales-report', blankMode: 'choice', answer: { subject: 'Request', body: '', blanks: ['Could you please', 'by', 'Please let me know'] } }));
  assert.equal(response.status, 200);
  const evaluation = await response.json();
  assert.equal(evaluation.mode, 'demo');
  assert.equal(evaluation.total, 100);
  assert.equal(calls.length, 0);
});
test('RAG feedback renders status and general-advice label without numeric scores', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const Feedback = load('src/components/rag-feedback.tsx').default;
  const html = renderToStaticMarkup(React.createElement(Feedback, { result: { ...result, feedback: [{ criterion_id: 'general-tip', category: 'general', explanation: '문단을 나눠 보세요.', suggestion: '문단 예시', evidence_ids: [] }] } }));
  assert.match(html, /요구사항 충족/);
  assert.match(html, /일반 조언/);
  assert.doesNotMatch(html, /\/ 100|score-number/);
});
test('withheld feedback describes an unconfirmed review without asserting missing company documents', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const Feedback = load('src/components/rag-feedback.tsx').default;
  const html = renderToStaticMarkup(React.createElement(Feedback, { result: { ...result, status: 'insufficient_evidence' } }));
  assert.match(html, /판단 보류 · 검토 확인 필요/);
  assert.doesNotMatch(html, /판단 보류 · 근거 부족/);
});
