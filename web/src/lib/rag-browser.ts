import { parseRagAnswer, parseRagEvaluation, requestForAnswer, type PendingRagRequest, type RagAnswer } from './rag-contract';

export type RagDraft = { answer: RagAnswer; pending: PendingRagRequest | null };
const draftKey = (userId: string, attemptId: string) => `rootkit-rag-draft-v1:${userId}:${attemptId}`;
export const activeAttemptKey = (userId: string, stage: number) => `rootkit-rag-active-v1:${userId}:${stage}`;
export function readRagDraft(userId: string, attemptId: string): RagDraft {
  const empty: RagDraft = { answer: { subject: '', body: '' }, pending: null };
  try {
    const input = JSON.parse(localStorage.getItem(draftKey(userId, attemptId)) || 'null');
    if (!input || typeof input.answer?.subject !== 'string' || typeof input.answer?.body !== 'string') return empty;
    const answer = { subject: input.answer.subject.slice(0, 200), body: input.answer.body.slice(0, 10000) };
    let pending: PendingRagRequest | null = null;
    if (typeof input.pending?.request_id === 'string' && /^[a-zA-Z0-9_-]{1,200}$/.test(input.pending.request_id)) {
      try { pending = { request_id: input.pending.request_id, answer: parseRagAnswer(input.pending.answer) }; } catch { /* Keep the editable draft even if retry data is corrupt. */ }
    }
    return { answer, pending };
  } catch { return empty; }
}
export function saveRagDraft(userId: string, attemptId: string, draft: RagDraft): boolean {
  try { localStorage.setItem(draftKey(userId, attemptId), JSON.stringify(draft)); return true; }
  catch { return false; }
}
export async function ragFetch<T>(path: string, parse: (input: unknown) => T, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    signal: AbortSignal.timeout(210000),
  });
  const input = await response.json().catch(() => null);
  if (!response.ok) throw new Error(response.status === 401 ? '로그인이 만료되었습니다. 다시 로그인해 주세요.' : input?.error || '요청을 처리하지 못했습니다. 다시 시도해 주세요.');
  return parse(input);
}
export async function evaluateRagDraft(attemptId: string, draft: RagDraft, persist: (next: RagDraft) => void) {
  const pending = requestForAnswer(draft.pending, draft.answer, () => crypto.randomUUID());
  persist({ ...draft, pending });
  const result = await ragFetch('/api/rag/evaluations', parseRagEvaluation, { attempt_id: attemptId, request_id: pending.request_id, answer: pending.answer });
  if (result.attempt_id !== attemptId || result.request_id !== pending.request_id) throw new Error('평가 결과가 요청과 일치하지 않습니다. 다시 시도해 주세요.');
  // A confirmed result ends this request, including a withheld result. Uncertain failures retain the ID for recovery.
  persist({ ...draft, pending: null });
  return result;
}
export function ragError(error: unknown) {
  return error instanceof Error && ['TimeoutError', 'AbortError'].includes(error.name)
    ? '응답 시간이 초과되었습니다. 답안은 유지됩니다. 이전 평가 결과 확인하기를 누르면 같은 요청의 완료 여부를 확인합니다.'
    : error instanceof Error ? error.message : '연결을 확인하고 다시 시도해 주세요.';
}
