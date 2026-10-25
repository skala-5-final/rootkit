import { agentRequest, toExercise, type Challenge } from '@/lib/agent';

export async function GET() {
  try {
    const [response, health] = await Promise.all([agentRequest('/challenges'), agentRequest('/health')]);
    if (!response.ok || !health.ok) throw new Error('Agent unavailable');
    const challenges: Challenge[] = await response.json();
    const { mode } = await health.json();
    if (!['live', 'replay'].includes(mode) || !challenges.length) throw new Error('Invalid agent response');
    return Response.json({ exercises: challenges.map(toExercise), mode });
  } catch {
    return Response.json({ error: '학습 에이전트에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.' }, { status: 503 });
  }
}
