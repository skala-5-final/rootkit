import 'server-only';
import type { NextRequest } from 'next/server';
import { sessionCookie, verifySession } from './session';
import { RagServiceError } from './rag-client';

export async function ragUser(request: NextRequest): Promise<string> {
  const session = await verifySession(request.cookies.get(sessionCookie)?.value);
  if (!session) throw new RagServiceError('로그인이 필요합니다.', 401, 'unauthorized');
  if (request.method !== 'GET') {
    const origin = request.headers.get('origin');
    const target = new URL(request.url);
    // Next may normalize request.url to localhost. The incoming Host retains the
    // authority the browser actually requested; forwarded host headers are not trusted.
    const host = request.headers.get('host');
    const expectedOrigin = host ? new URL(`${target.protocol}//${host}`).origin : target.origin;
    if ((origin && origin !== expectedOrigin) || request.headers.get('sec-fetch-site') === 'cross-site') throw new RagServiceError('허용되지 않은 요청 출처입니다.', 403, 'forbidden');
  }
  return session.userId;
}
export async function ragInput(request: Request, keys: string[]) {
  if (!request.headers.get('content-type')?.includes('application/json')) throw new RagServiceError('JSON 요청이 필요합니다.', 400, 'invalid_request');
  if (Number(request.headers.get('content-length') || 0) > 100000) throw new RagServiceError('요청이 너무 큽니다.', 413, 'invalid_request');
  const raw = await request.text();
  if (raw.length > 100000) throw new RagServiceError('요청이 너무 큽니다.', 413, 'invalid_request');
  let input: unknown;
  try { input = JSON.parse(raw); } catch { throw new RagServiceError('올바른 JSON 요청이 필요합니다.', 400, 'invalid_request'); }
  if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).some(key => !keys.includes(key))) throw new RagServiceError('허용되지 않은 요청 필드입니다.', 422, 'invalid_request');
  return input as Record<string, unknown>;
}
export function ragId(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-zA-Z0-9_-]{1,200}$/.test(value)) throw new RagServiceError('학습 또는 요청 ID를 확인해 주세요.', 422, 'invalid_request');
  return value;
}
export function ragJson(value: unknown) { return Response.json(value, { headers: { 'Cache-Control': 'private, no-store' } }); }
export function ragFailure(error: unknown) {
  const known = error instanceof RagServiceError ? error : new RagServiceError('요청을 처리할 수 없습니다.', 500, 'internal_error');
  return Response.json({ error: known.message, code: known.code }, { status: known.status, headers: { 'Cache-Control': 'private, no-store' } });
}
