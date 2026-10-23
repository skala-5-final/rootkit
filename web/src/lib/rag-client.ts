import 'server-only';
import { InvalidRagResponse, parseRagAttempt, parseRagEvaluation, parseRagHistory, type RagAnswer, type RagStage } from './rag-contract';

export class RagServiceError extends Error {
  constructor(message: string, public readonly status: number, public readonly code: string) { super(message); }
}
const messages: Record<string, string> = {
  no_active_catalog: '활성화된 문제집이 없습니다. 담당자가 데이터 반입·문제 생성·검토·활성화를 완료해야 합니다.',
  no_exercises: '활성 문제집에 이 단계의 검토 통과 문제가 없습니다.',
  request_conflict: '같은 요청 ID에 다른 답안이 연결되어 있습니다. 답안을 수정한 뒤 다시 제출해 주세요.',
};
async function call<T>(path: string, parse: (value: unknown) => T, body?: unknown): Promise<T> {
  const base = process.env.AI_API_BASE_URL;
  const token = process.env.AI_API_TOKEN;
  if (!base || !token || token === 'change-me') throw new RagServiceError('AI 서비스 연결 설정이 없습니다. 담당자에게 문의해 주세요.', 503, 'service_not_configured');
  let url: URL;
  try {
    url = new URL(`${base.replace(/\/$/, '')}${path}`);
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error();
  } catch { throw new RagServiceError('AI 서비스 주소 설정을 확인해 주세요.', 503, 'service_not_configured'); }
  try {
    const response = await fetch(url, {
      method: body === undefined ? 'GET' : 'POST', cache: 'no-store', redirect: 'error',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(200000),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      const code = typeof data?.code === 'string' && /^[a-z_]{1,80}$/.test(data.code) ? data.code : 'service_error';
      const status = [400, 404, 409, 422, 503].includes(response.status) ? response.status : 502;
      const message = messages[code] ?? (status === 404 ? '이 학습 기록을 찾을 수 없거나 접근할 수 없습니다.' : status === 409 ? '요청이 충돌했습니다. 잠시 후 다시 제출해 주세요.' : status === 503 ? 'AI 모델 설정 또는 서비스 상태를 확인해야 합니다. 답안은 유지됩니다.' : 'AI 평가를 완료하지 못했습니다. 잠시 후 같은 답안으로 다시 제출해 주세요.');
      throw new RagServiceError(message, status, code);
    }
    return parse(await response.json());
  } catch (error) {
    if (error instanceof RagServiceError) throw error;
    if (error instanceof InvalidRagResponse || error instanceof SyntaxError) throw new RagServiceError('AI 서비스 응답을 확인할 수 없습니다. 답안은 유지됩니다.', 502, 'invalid_response');
    if (error instanceof Error && ['TimeoutError', 'AbortError'].includes(error.name)) throw new RagServiceError('평가 응답 시간이 초과되었습니다. 같은 답안으로 다시 제출하면 기존 요청을 이어서 확인합니다.', 504, 'service_timeout');
    throw new RagServiceError('AI 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.', 502, 'service_unavailable');
  }
}
export async function createRagAttempt(userId: string, stage: RagStage) {
  const result = await call('/attempts', parseRagAttempt, { user_id: userId, stage });
  if (result.exercise.stage !== stage) throw new RagServiceError('문제 단계가 요청과 일치하지 않습니다.', 502, 'invalid_response');
  return result;
}
export async function getRagAttempt(userId: string, id: string) {
  const result = await call(`/attempts/${encodeURIComponent(id)}?${new URLSearchParams({ user_id: userId })}`, parseRagAttempt);
  if (result.attempt_id !== id) throw new RagServiceError('학습 기록이 요청과 일치하지 않습니다.', 502, 'invalid_response');
  return result;
}
export async function evaluateRag(userId: string, attemptId: string, requestId: string, answer: RagAnswer) {
  const result = await call('/evaluations', parseRagEvaluation, { user_id: userId, attempt_id: attemptId, request_id: requestId, answer });
  if (result.attempt_id !== attemptId || result.request_id !== requestId) throw new RagServiceError('평가 결과가 요청과 일치하지 않습니다.', 502, 'invalid_response');
  return result;
}
export function getRagHistory(userId: string) {
  return call(`/history?${new URLSearchParams({ user_id: userId })}`, parseRagHistory);
}
