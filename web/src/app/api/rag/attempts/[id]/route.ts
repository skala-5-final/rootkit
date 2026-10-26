import type { NextRequest } from 'next/server';
import { getRagAttempt } from '@/lib/rag-client';
import { ragFailure, ragId, ragJson, ragUser } from '@/lib/rag-http';

export async function GET(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  try {
    const userId = await ragUser(request);
    const { id } = await context.params;
    return ragJson(await getRagAttempt(userId, ragId(id)));
  } catch (error) { return ragFailure(error); }
}
