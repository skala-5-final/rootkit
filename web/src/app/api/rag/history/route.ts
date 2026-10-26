import type { NextRequest } from 'next/server';
import { getRagHistory } from '@/lib/rag-client';
import { ragFailure, ragJson, ragUser } from '@/lib/rag-http';

export async function GET(request: NextRequest) {
  try { return ragJson(await getRagHistory(await ragUser(request))); }
  catch (error) { return ragFailure(error); }
}
