import { NextRequest, NextResponse } from 'next/server';
import { agentRequest, toEvaluation, type Challenge } from '@/lib/agent';
import { agentCookie, readAgentToken, signAgentToken, cookieOptions, sessionCookie, verifySession } from '@/lib/session';

export async function POST(request: NextRequest) {
  const user = await verifySession(request.cookies.get(sessionCookie)?.value);
  if (!user) return Response.json({ error: '로그인이 필요합니다.' }, { status: 401 });
  const input = await request.json().catch(() => null);
  if (typeof input?.exerciseId !== 'string' || !/^en_\d+_(rewrite|compose)$/.test(input.exerciseId) ||
      typeof input.answer?.subject !== 'string' || typeof input.answer?.body !== 'string' ||
      !input.answer.subject.trim() || !input.answer.body.trim() || input.answer.subject.length > 200 || input.answer.body.length > 10000) {
    return Response.json({ error: '문제, 제목(200자 이내), 본문(10,000자 이내)을 확인해 주세요.' }, { status: 422 });
  }
  try {
    const challengeResponse = await agentRequest(`/challenges/${input.exerciseId}`);
    if (challengeResponse.status === 404) return Response.json({ error: '존재하지 않는 문제입니다.' }, { status: 404 });
    if (!challengeResponse.ok) throw new Error('Agent unavailable');
    const challenge: Challenge = await challengeResponse.json();
    let token = await readAgentToken(request.cookies.get(agentCookie)?.value, user.userId);
    if (!token) {
      const session = await agentRequest('/sessions', { method: 'POST' });
      if (!session.ok) throw new Error('Cannot create agent session');
      token = (await session.json()).token;
      if (typeof token !== 'string' || !token) throw new Error('Invalid agent session');
    }
    const upstream = await agentRequest(`/challenges/${input.exerciseId}/attempts`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ subject: input.answer.subject.trim(), body: input.answer.body.trim() }),
    });
    if (upstream.status === 401) {
      const response = NextResponse.json({ error: '에이전트 세션이 만료되었습니다. 다시 제출해 주세요.' }, { status: 409 });
      response.cookies.set(agentCookie, '', { ...cookieOptions(request), maxAge: 0 });
      return response;
    }
    if (!upstream.ok) {
      const data = await upstream.json().catch(() => ({}));
      const replay = typeof data.detail === 'string' && data.detail.startsWith('Replay mode only accepts');
      return Response.json({ error: replay ? '현재 replay 모드는 등록된 예시 답안만 지원합니다. 자유 작문 채점에는 서버의 live 모드와 모델 설정이 필요합니다.' : '에이전트가 채점하지 못했습니다. 작성 내용은 유지됩니다. 서버 설정을 확인하고 다시 시도해 주세요.' }, { status: upstream.status === 422 ? 422 : 503 });
    }
    const { feedback } = await upstream.json();
    const response = NextResponse.json(toEvaluation(feedback, challenge));
    response.cookies.set(agentCookie, await signAgentToken(token, user.userId), cookieOptions(request));
    return response;
  } catch {
    return Response.json({ error: '에이전트 연결 또는 응답에 문제가 있습니다. 작성 내용은 유지됩니다.' }, { status: 503 });
  }
}
