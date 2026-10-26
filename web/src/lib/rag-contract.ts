// Only learner-visible fields belong here. Internal criteria and review data stay on the AI server.
export type RagStage = 1 | 2;
export type RagAnswer = { subject: string; body: string };
export type RagFact = { id: string; value: string; kind: string; origin: 'source' | 'exercise'; source_ids: string[] };
export type RagExercise = {
  id: string; version: number; dataset_id: string; dataset_version: number;
  stage: RagStage; language: string; recipient_group: 'customer' | 'general';
  title: string; scenario: string; requirements: string[]; facts: RagFact[];
  original: string | null; subject: string; recipient: string; source_ids: string[];
};
export type RagAttempt = { attempt_id: string; exercise: RagExercise };
export type RagEvaluation = {
  attempt_id: string; request_id: string; total: null;
  status: 'match' | 'needs_revision' | 'insufficient_evidence'; summary: string;
  feedback: { criterion_id: string; category: 'company' | 'task' | 'general'; explanation: string; suggestion: string; evidence_ids: string[] }[];
};
export type RagHistoryItem = RagAttempt & { submissions: { request_id: string; answer: RagAnswer; result: RagEvaluation; created_at: string }[] };

export class InvalidRagResponse extends Error {
  constructor() { super('AI 서비스 응답 형식이 올바르지 않습니다.'); }
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new InvalidRagResponse();
  return value as Record<string, unknown>;
}
function text(value: unknown, max = 20000, empty = false): string {
  if (typeof value !== 'string' || value.length > max || (!empty && !value.trim())) throw new InvalidRagResponse();
  return value;
}
function integer(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) throw new InvalidRagResponse();
  return value;
}
function list<T>(value: unknown, parse: (item: unknown) => T, max = 500): T[] {
  if (!Array.isArray(value) || value.length > max) throw new InvalidRagResponse();
  return value.map(parse);
}
function texts(value: unknown): string[] { return list(value, item => text(item, 4000)); }
function choice<T extends string | number>(value: unknown, choices: readonly T[]): T {
  if (!choices.includes(value as T)) throw new InvalidRagResponse();
  return value as T;
}
export function parseRagAnswer(value: unknown): RagAnswer {
  const input = record(value);
  return { subject: text(input.subject, 200), body: text(input.body, 10000) };
}
export function parseRagExercise(value: unknown): RagExercise {
  const input = record(value);
  const stage = choice(input.stage, [1, 2] as const);
  const original = input.original === null ? null : text(input.original, 20000);
  if (stage === 1 && original === null) throw new InvalidRagResponse();
  const requirements = texts(input.requirements);
  const source_ids = texts(input.source_ids);
  if (!requirements.length || !source_ids.length) throw new InvalidRagResponse();
  return {
    id: text(input.id, 200), version: integer(input.version), dataset_id: text(input.dataset_id, 200),
    dataset_version: integer(input.dataset_version), stage,
    language: text(input.language, 40), recipient_group: choice(input.recipient_group, ['customer', 'general'] as const),
    title: text(input.title, 500), scenario: text(input.scenario), requirements,
    facts: list(input.facts, value => {
      const fact = record(value);
      return { id: text(fact.id, 200), value: text(fact.value, 4000),
        kind: choice(fact.kind, ['date', 'time', 'timezone', 'quantity', 'amount', 'target', 'intent', 'status', 'other'] as const),
        origin: choice(fact.origin, ['source', 'exercise'] as const), source_ids: texts(fact.source_ids ?? []) };
    }), original, subject: text(input.subject, 200, true), recipient: text(input.recipient, 500), source_ids,
  };
}
export function parseRagAttempt(value: unknown): RagAttempt {
  const input = record(value);
  return { attempt_id: text(input.attempt_id, 200), exercise: parseRagExercise(input.exercise) };
}
export function parseRagEvaluation(value: unknown): RagEvaluation {
  const input = record(value);
  if (input.total !== null) throw new InvalidRagResponse();
  return {
    attempt_id: text(input.attempt_id, 200), request_id: text(input.request_id, 200), total: null,
    status: choice(input.status, ['match', 'needs_revision', 'insufficient_evidence'] as const), summary: text(input.summary),
    feedback: list(input.feedback, value => {
      const item = record(value);
      return { criterion_id: text(item.criterion_id, 200), category: choice(item.category, ['company', 'task', 'general'] as const),
        explanation: text(item.explanation), suggestion: text(item.suggestion, 20000, true), evidence_ids: texts(item.evidence_ids) };
    }),
  };
}
export function parseRagHistory(value: unknown): { items: RagHistoryItem[] } {
  const input = record(value);
  return { items: list(input.items, value => {
    const item = record(value);
    const attempt = parseRagAttempt(item);
    return { ...attempt, submissions: list(item.submissions, value => {
      const submission = record(value);
      const request_id = text(submission.request_id, 200);
      const result = parseRagEvaluation(submission.result);
      const created_at = text(submission.created_at, 80);
      if (result.attempt_id !== attempt.attempt_id || result.request_id !== request_id || !Number.isFinite(Date.parse(created_at))) throw new InvalidRagResponse();
      return { request_id, answer: parseRagAnswer(submission.answer), result, created_at };
    }, 1000) };
  }, 1000) };
}

// Reuse a request identifier after a timeout, but never for an edited answer.
export type PendingRagRequest = { request_id: string; answer: RagAnswer };
export function requestForAnswer(previous: PendingRagRequest | null, answer: RagAnswer, createId: () => string): PendingRagRequest {
  if (previous && previous.answer.subject === answer.subject && previous.answer.body === answer.body) return previous;
  return { request_id: createId(), answer: { ...answer } };
}
