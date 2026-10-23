import type { NextRequest } from 'next/server';
import { createRagAttempt, RagServiceError } from '@/lib/rag-client';
import { ragFailure, ragInput, ragJson, ragUser } from '@/lib/rag-http';

export async function POST(request: NextRequest) {
  try {
    const userId = await ragUser(request);
    const input = await ragInput(request, ['stage']);
    if (input.stage !== 1 && input.stage !== 2) throw new RagServiceError('STEP 1 또는 STEP 2를 선택해 주세요.', 422, 'invalid_request');
    return ragJson(await createRagAttempt(userId, input.stage));
  } catch (error) { return ragFailure(error); }
}
