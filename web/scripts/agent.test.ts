import { test } from 'node:test';
import assert from 'node:assert/strict';
import { toEvaluation, toExercise, type Challenge, type AgentFeedback } from '../src/lib/agent.ts';
import { readAgentToken, signAgentToken } from '../src/lib/session.ts';

const challenge: Challenge = { id: 'en_001_compose', exercise_type: 'compose', title: 'Request', scenario_type: 'request', instructions: 'Write', recipient: { name: 'Alex', relationship: 'colleague' }, scenario: 'Request report', starter_email: null, requirements: [{ id: 'r1', description: 'Include deadline' }], hint: 'Be clear' };
const feedback: AgentFeedback = { mode: 'replay', complete: false, scores: { content: 30, tone: 25, structure: 20, language: 15, total: 90 }, requirement_checks: [{ requirement_id: 'r1', met: false }], strengths: [], issues: [{ explanation: 'Missing deadline.', revision_hint: 'Add a date.' }], contradictions: [], revision: { resolved_requirement_ids: [], regressed_requirement_ids: ['r1'] } };

test('maps agent curriculum and preserves incomplete status despite a high score', () => {
  assert.equal(toExercise(challenge).stage, 2);
  assert.equal(toExercise({ ...challenge, scenario_label: '자료 요청' }).tag, '자료 요청');
  assert.equal(toExercise({ ...challenge, exercise_type: 'rewrite' }).stage, 1);
  const result = toEvaluation(feedback, challenge);
  assert.equal(result.complete, false);
  assert.equal(result.total, 90);
  assert.equal(result.mode, 'replay');
  assert.deepEqual(result.checks, [{ label: 'Include deadline', passed: false }]);
  assert.ok(result.feedback.includes('다시 확인: Include deadline'));
  assert.throws(() => toEvaluation({ ...feedback, requirement_checks: [] }, challenge));
});

test('agent session cookie is signed and bound to the logged-in user', async () => {
  process.env.JWT_SECRET = 'integration-test-only-secret-at-least-32-characters';
  const cookie = await signAgentToken('private-bearer', 'user-a');
  assert.equal(await readAgentToken(cookie, 'user-a'), 'private-bearer');
  assert.equal(await readAgentToken(cookie, 'user-b'), null);
  assert.equal(await readAgentToken(`${cookie}tampered`, 'user-a'), null);
  assert.equal(await readAgentToken(undefined, 'user-a'), null);
});
