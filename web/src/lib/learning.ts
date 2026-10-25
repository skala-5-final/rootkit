export type Stage = 0 | 1 | 2;
export type BlankMode = 'choice' | 'input';
export type SessionConfig = { count: number | 'infinite'; blankMode: BlankMode };
export type Draft = { subject: string; body: string; blanks: string[] };
export type Score = { label: string; score: number; max: number; comment: string };
export type Evaluation = { total: number; summary: string; scores: Score[]; feedback: string[]; checks: { label: string; passed: boolean }[]; mode: 'demo' | 'replay' | 'live'; complete?: boolean };
export type Submission = { id: string; stage: Stage; exerciseId?: string; title?: string; draft: Draft; evaluation: Evaluation; createdAt: string };

// 빈칸 정답은 서버(demo-evaluation.ts)에만 둔다.
export type Blank = { label: string; before: string; after: string; options: string[] };
export type Exercise = {
  id: string;
  stage: Stage;
  title: string;
  tag: string;
  description: string;
  recipient: string;
  scenario: string;
  subject: string;
  original: string | null;
  requirements: string[];
  hint: string;
  reference: string;
  blanks?: Blank[];
};

export const stageNames = ['빈칸 채우기', '이메일 다듬기', '상황별 작성'] as const;
export const stageMeta: Record<Stage, { level: string; subtitle: string; minutes: number }> = {
  0: { level: '입문', subtitle: '핵심 표현을 익히는 작은 시작', minutes: 1.5 },
  1: { level: '기초', subtitle: '일상 표현을 비즈니스 표현으로', minutes: 6 },
  2: { level: '실전', subtitle: '업무 상황을 한 통의 메일로', minutes: 10 },
};
export const blankModeNames: Record<BlankMode, string> = { choice: '보기 선택', input: '직접 입력' };
export const countOptions = [3, 5, 10, 'infinite'] as const;

export const exercisePool: Record<Stage, Exercise[]> = {
  0: [
    {
      id: 'b-sales-report', stage: 0, title: '정중한 요청, 한 문장부터', tag: '자료 요청',
      description: '문맥에 맞는 표현으로 이메일의 빈칸을 완성해 보세요.', recipient: 'Alex Morgan · Sales Team',
      scenario: '금요일 회의를 준비하기 위해 영업팀 Alex에게 이번 달 영업 실적 자료를 요청하려고 합니다.',
      subject: "Request for this month's sales report", original: null,
      requirements: ['정중하게 자료 요청하기', '요청 기한 연결하기', '일정 조율 가능 여부 전하기'],
      hint: 'Could you please + 동사원형은 정중한 요청에 쓰여요. 마감 시점 앞에는 by를 사용해요.',
      reference: '요청 메일에는 필요한 자료, 사용 목적, 기한을 명확히 적고 상대방의 일정도 배려합니다.',
      blanks: [
        { label: '정중한 요청', before: 'Hi Alex,\n\n', after: " share this month's sales report", options: ['You must', 'Could you please', 'Why not'] },
        { label: '마감 시점', before: ' ', after: ' Friday at 10 a.m. KST?\nI need it to prepare for our Friday meeting.\n\n', options: ['since', 'during', 'by'] },
        { label: '일정 조율', before: '', after: ' if you need more time.\n\nBest regards,\nRookie', options: ['Please let me know', "Don't tell me", 'You should finish'] },
      ],
    },
    {
      id: 'b-agenda', stage: 0, title: '회의 안건 공유하기', tag: '회의 준비',
      description: '회의 전에 안건을 공유하는 메일을 완성해 보세요.', recipient: 'Jamie Lee · Client',
      scenario: '목요일 고객 미팅을 앞두고 Jamie에게 회의 일정을 다시 확인하고 안건 파일을 공유하려고 합니다.',
      subject: "Agenda for Thursday's meeting", original: null,
      requirements: ['메일의 목적 밝히기', '첨부 파일 안내하기', '첨부 상태 표현하기'],
      hint: "I'm writing to ~ 는 메일의 목적을 밝힐 때 써요. 첨부 파일은 Please find ~ attached.",
      reference: '회의 전 메일에는 일정 재확인, 안건, 첨부 자료를 짧게 정리합니다.',
      blanks: [
        { label: '메일의 목적', before: 'Hi Jamie,\n\nI\'m ', after: ' to confirm our meeting on Thursday at 3 p.m. KST.\n', options: ['writing', 'saying', 'telling'] },
        { label: '첨부 안내', before: 'Please ', after: ' the agenda ', options: ['look', 'find', 'see'] },
        { label: '첨부 상태', before: '', after: '.\n\nBest regards,\nRookie', options: ['attach', 'attaching', 'attached'] },
      ],
    },
    {
      id: 'b-thanks', stage: 0, title: '감사 인사로 마무리하기', tag: '감사',
      description: '도움을 준 선배에게 보내는 감사 메일을 완성해 보세요.', recipient: 'Ms. Park · HR Team',
      scenario: '인사팀 박 매니저님이 온보딩 서류 작성을 빠르게 도와주셨습니다. 감사 인사와 함께 추가 안내를 기다린다고 전하세요.',
      subject: 'Thank you for your help', original: null,
      requirements: ['감사의 대상 연결하기', '도움에 감사 표현하기', '회신을 기다린다고 전하기'],
      hint: 'Thank you for + 명사, look forward to + 동사ing 형태를 기억하세요.',
      reference: '감사 메일은 구체적으로 무엇이 도움이 되었는지 언급하면 더 진정성 있게 전달됩니다.',
      blanks: [
        { label: '감사의 대상', before: 'Dear Ms. Park,\n\nThank you ', after: ' your quick response.\n', options: ['to', 'for', 'about'] },
        { label: '감사 표현', before: 'I really ', after: ' your help with the onboarding documents.\n', options: ['appreciate', 'thank', 'enjoy'] },
        { label: '회신 기대', before: 'I look forward to ', after: ' from you.\n\nBest regards,\nRookie', options: ['hear', 'hearing', 'heard'] },
      ],
    },
    {
      id: 'b-delay', stage: 0, title: '늦어진 보고, 사과하기', tag: '사과',
      description: '주간 보고가 늦어진 상황을 정중하게 알리는 메일을 완성해 보세요.', recipient: 'Project Team',
      scenario: '주간 보고서 제출이 늦어졌습니다. 팀에 사과하고 오늘 업무 종료 전까지 보내겠다고 안내하세요.',
      subject: 'Weekly report update', original: null,
      requirements: ['지연에 대해 사과하기', '전달 기한 안내하기', '양해에 감사하기'],
      hint: 'apologize for ~ 로 사과하고, by the end of the day로 기한을 알려요.',
      reference: '지연 안내는 사과, 새 기한, 감사 순서로 간결하게 작성합니다.',
      blanks: [
        { label: '사과 표현', before: 'Hi team,\n\nI ', after: ' for the delay in sending the weekly report.\n', options: ['apologize', 'sorry', 'excuse'] },
        { label: '전달 기한', before: 'I will send it ', after: ' the end of the day.\n', options: ['until', 'by', 'since'] },
        { label: '양해 감사', before: 'Thank you for your ', after: '.\n\nBest regards,\nRookie', options: ['understand', 'understood', 'understanding'] },
      ],
    },
  ],
  1: [
    {
      id: 'r-sales-report', stage: 1, title: '조금 더 정중하게, 자료 요청하기', tag: '업무 요청',
      description: '기본 이메일을 동료에게 보내기 적절한 비즈니스 이메일로 다듬어 보세요.', recipient: 'Alex Morgan · Sales Team',
      scenario: '금요일 회의 준비를 위해 이번 달 영업 실적 자료가 필요합니다. 영업팀 Alex에게 금요일 오전 10시(KST)까지 자료를 요청해 주세요.',
      subject: 'Send me the sales report',
      original: "Hi Alex,\n\nI need this month's sales report for our Friday meeting.\nSend it to me by Friday at 10 a.m. KST.\nTell me if you can't.\n\nThanks,\nRookie",
      requirements: ['이번 달 영업 실적 자료와 회의 준비 목적 전달', '금요일 오전 10시(KST) 마감 안내', '정중한 요청과 일정 조율 문구 포함'],
      hint: 'Could you please share…? / Please let me know if you need more time.',
      reference: '자료 요청 시 요청 목적과 마감 시점을 함께 전달합니다. 상대방이 일정을 조율할 수 있도록 회신 문장을 덧붙입니다.',
    },
    {
      id: 'r-cancel-meeting', stage: 1, title: '회의 취소, 부드럽게 알리기', tag: '일정 변경',
      description: '퉁명스럽게 느껴지는 회의 취소 메일을 정중하게 다듬어 보세요.', recipient: 'Chris Kim · Marketing',
      scenario: '내일 예정된 마케팅 회의를 급한 업무로 취소해야 합니다. Chris에게 사과하고 다음 주로 일정을 다시 잡자고 제안하세요.',
      subject: 'Meeting canceled',
      original: "Chris,\n\nThe meeting tomorrow is canceled. I'm busy.\nWe will do it next week. Tell me your free time.\n\nRookie",
      requirements: ['회의 취소 사실과 사과 전달', '다음 주로 일정 재조정 제안', '가능한 시간을 정중하게 묻기'],
      hint: "I'm afraid we need to reschedule… / Could you let me know when you are available next week?",
      reference: '일정 취소 메일은 사과와 함께 대안을 먼저 제시하면 상대방의 부담이 줄어듭니다.',
    },
  ],
  2: [
    {
      id: 'w-reschedule', stage: 2, title: '변경된 일정을 고객에게 안내하기', tag: '일정 변경',
      description: '업무 상황을 읽고 고객에게 보낼 이메일을 직접 작성해 보세요.', recipient: 'Jamie Lee · Client',
      scenario: '당신은 프로젝트 운영팀의 신입사원입니다. 내부 일정 변경으로 고객사 Jamie와의 신규 서비스 도입 미팅을 옮겨야 합니다.\n\n기존 일정: 2026년 11월 4일 수요일 오후 2시 (KST)\n제안 일정: 2026년 11월 5일 목요일 오후 3시 (KST)\n미팅 내용: 신규 서비스 도입 일정 논의',
      subject: '', original: null,
      requirements: ['일정 변경 사유와 사과 전달', '새로운 날짜·시간·시간대 제시', '제안한 일정이 가능한지 회신 요청'],
      hint: 'Would it be possible to reschedule…? / I apologize for any inconvenience. / Would this time work for you?',
      reference: '일정을 바꿀 때에는 변경 사유를 간결하게 설명하고, 대체 일정과 시간대를 제시한 뒤 상대방의 가능 여부를 확인합니다.',
    },
    {
      id: 'w-welcome', stage: 2, title: '새 팀원에게 첫 출근 안내하기', tag: '온보딩',
      description: '새로 합류하는 팀원에게 첫 출근 정보를 안내하는 메일을 작성해 보세요.', recipient: 'Mina Choi · New Hire',
      scenario: '다음 주에 해외 지사에서 Mina가 팀에 합류합니다. 환영 인사와 함께 첫 출근 정보를 안내하세요.\n\n첫 출근: 11월 9일 월요일 오전 9시 (KST)\n장소: 본사 3층 로비\n준비물: 신분증(ID)',
      subject: '', original: null,
      requirements: ['환영 인사 전하기', '첫 출근 날짜·시간·장소 안내', '준비물 안내'],
      hint: "We're excited to have you on the team. / Please bring your ID.",
      reference: '환영 메일은 따뜻한 인사로 시작하고, 첫날 필요한 정보를 목록처럼 간결하게 정리합니다.',
    },
  ],
};

export function findExercise(id: string): Exercise | undefined {
  return Object.values(exercisePool).flat().find(x => x.id === id);
}
export function emptyDraft(exercise: Exercise): Draft {
  return { subject: exercise.stage === 0 ? exercise.subject : '', body: '', blanks: (exercise.blanks || []).map(() => '') };
}
export function blankBody(exercise: Exercise, values: string[]) {
  return (exercise.blanks || []).map((blank, i) => blank.before + (values[i] || `[빈칸 ${i + 1}]`) + blank.after).join('');
}
export function isStage(value: unknown): value is Stage { return value === 0 || value === 1 || value === 2; }
export function estimateMinutes(stage: Stage, config: SessionConfig) {
  if (config.count === 'infinite') return null;
  const perItem = stage === 0 && config.blankMode === 'input' ? 2 : stageMeta[stage].minutes;
  return Math.max(1, Math.round(perItem * config.count));
}
export function parseSessionConfig(params: { count?: string | string[]; type?: string | string[] }): SessionConfig {
  const count = params.count === 'infinite' ? 'infinite' : [3, 5, 10].includes(Number(params.count)) ? Number(params.count) : 5;
  return { count, blankMode: params.type === 'input' ? 'input' : 'choice' };
}
