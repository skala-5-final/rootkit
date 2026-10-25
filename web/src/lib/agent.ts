import type { Evaluation, Exercise } from './learning';

export type Challenge = {
  id: string; exercise_type: 'rewrite' | 'compose'; title: string; scenario_type: string; scenario_label?: string;
  instructions: string; recipient: { name: string; relationship: string }; scenario: string;
  starter_email: { subject: string; body: string } | null;
  requirements: { id: string; description: string }[]; hint: string;
};
export type AgentFeedback = {
  mode: 'live' | 'replay'; complete: boolean;
  scores: { content: number; tone: number; structure: number; language: number; total: number };
  requirement_checks: { requirement_id: string; met: boolean }[];
  strengths: string[]; issues: { explanation: string; revision_hint: string }[];
  contradictions: { explanation: string }[];
  revision: { resolved_requirement_ids: string[]; regressed_requirement_ids: string[] };
};
export function toExercise(c: Challenge): Exercise {
  if (!['rewrite', 'compose'].includes(c.exercise_type)) throw new Error('Unsupported challenge');
  return { id: c.id, stage: c.exercise_type === 'rewrite' ? 1 : 2, title: c.title,
    tag: c.scenario_label || c.scenario_type, description: c.instructions, recipient: `${c.recipient.name} · ${c.recipient.relationship}`,
    scenario: c.scenario, subject: c.starter_email?.subject || '', original: c.starter_email?.body || null,
    requirements: c.requirements.map(r => r.description), hint: c.hint,
    reference: '에이전트 교육 과정 · 학습용 가상 자료' };
}
export function toEvaluation(f: AgentFeedback, c: Challenge): Evaluation {
  if (!['live', 'replay'].includes(f.mode) || typeof f.complete !== 'boolean' ||
      !Number.isFinite(f.scores.total) || f.scores.total < 0 || f.scores.total > 100 ||
      f.requirement_checks.length !== c.requirements.length ||
      c.requirements.some(r => f.requirement_checks.filter(x => x.requirement_id === r.id && typeof x.met === 'boolean').length !== 1)) {
    throw new Error('Invalid agent feedback');
  }
  const label = (id: string) => c.requirements.find(r => r.id === id)?.description || id;
  return { total: f.scores.total, mode: f.mode, complete: f.complete,
    summary: f.complete ? '필수 요구사항을 충족했어요.' : '아직 완료되지 않았어요. 필수 요구사항과 수정 안내를 확인해 주세요.',
    scores: (['content', 'tone', 'structure', 'language'] as const).map((key, i) => ({
      label: ['필수 정보', '정중한 표현', '문서 구성', '언어'][i], score: f.scores[key], max: [40, 25, 20, 15][i], comment: '',
    })),
    checks: c.requirements.map(r => ({ label: r.description, passed: f.requirement_checks.find(x => x.requirement_id === r.id)!.met })),
    feedback: [...f.strengths, ...f.issues.map(i => `${i.explanation} ${i.revision_hint}`),
      ...f.contradictions.map(i => i.explanation),
      ...f.revision.resolved_requirement_ids.map(id => `개선됨: ${label(id)}`),
      ...f.revision.regressed_requirement_ids.map(id => `다시 확인: ${label(id)}`)] };
}
export async function agentRequest(path: string, init?: RequestInit) {
  const base = process.env.AI_API_BASE_URL;
  if (!base) throw new Error('AI_API_BASE_URL is missing');
  return fetch(`${base.replace(/\/$/, '')}${path}`, { ...init, cache: 'no-store', signal: AbortSignal.timeout(110000) });
}
