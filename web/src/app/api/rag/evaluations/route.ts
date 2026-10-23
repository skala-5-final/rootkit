import type { NextRequest } from 'next/server';
import { evaluateRag, RagServiceError } from '@/lib/rag-client';
import { parseRagAnswer } from '@/lib/rag-contract';
import { ragFailure, ragId, ragInput, ragJson, ragUser } from '@/lib/rag-http';

export async function POST(request: NextRequest) {
  try {
    const userId = await ragUser(request);
    const input = await ragInput(request, ['attempt_id', 'request_id', 'answer']);
    const attemptId = ragId(input.attempt_id);
    const requestId = ragId(input.request_id);
    let answer;
    try { answer = parseRagAnswer(input.answer); }
    catch { throw new RagServiceError('제목(200자 이내)과 본문(10,000자 이내)을 모두 작성해 주세요.', 422, 'invalid_answer'); }
    return ragJson(await evaluateRag(userId, attemptId, requestId, answer));
  } catch (error) { return ragFailure(error); }
}
