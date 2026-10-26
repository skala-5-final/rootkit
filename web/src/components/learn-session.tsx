'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { blankBody, blankModeNames, emptyDraft, exercisePool, stageMeta, stageNames, type Draft, type Evaluation, type Exercise, type SessionConfig, type Stage, type Submission } from '@/lib/learning';
import BlankEditor from './blank-editor';
import { DemoNote, type Store } from './rootkit';

type Props = { stage: Stage; config: SessionConfig; userName: string; store: Store; persist: (next: Store) => boolean; storageOk: boolean };

// 클라이언트에서만 마운트되므로(로그인 확인 후) 초기 셔플이 하이드레이션과 충돌하지 않는다.
function shuffled(length: number) {
  const order = Array.from({ length }, (_, i) => i);
  for (let i = order.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [order[i], order[j]] = [order[j], order[i]]; }
  return order;
}

export default function LearnSession(props: Props) {
  const [data, setData] = useState<{ exercises: Exercise[]; mode: 'live' | 'replay' } | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (props.stage === 0) return;
    const controller = new AbortController();
    fetch('/api/agent/challenges', { signal: controller.signal }).then(async response => {
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '문제를 불러오지 못했습니다.');
      if (!result.exercises.some((e: Exercise) => e.stage === props.stage)) throw new Error('이 단계의 문제가 없습니다.');
      setData(result);
    }).catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [props.stage, retry]);
  if (props.stage === 0) return <Session {...props} pool={exercisePool[0]} />;
  if (!data) return <main className="content-width"><p role={error ? 'alert' : 'status'}>{error || '에이전트의 학습 문제를 불러오고 있어요…'}</p>{error && <button className="button secondary" onClick={() => { setError(''); setRetry(retry + 1); }}>다시 연결</button>} <Link href="/kits">학습 키트로</Link></main>;
  return <><p className="content-width" role="status">{data.mode === 'replay' ? 'Replay 모드 · 등록된 예시 답안만 채점할 수 있습니다. 자유 작문에는 live 모드가 필요합니다.' : 'AI 채점 · 답안과 최근 수정 기록이 모델 제공자에게 전송됩니다.'}</p><Session {...props} pool={data.exercises.filter(e => e.stage === props.stage)} /></>;
}

function Session({ stage, config, userName, store, persist, storageOk, pool }: Props & { pool: Exercise[] }) {
  const router = useRouter();
  const [order, setOrder] = useState(() => shuffled(pool.length));
  const [index, setIndex] = useState(0);
  const [completedCount, setCompletedCount] = useState(0);
  const [finished, setFinished] = useState(false);
  const infinite = config.count === 'infinite';
  const total = infinite ? null : config.count as number;
  const exercise = pool[order[index % pool.length]];

  function next() {
    const nextCount = completedCount + 1;
    setCompletedCount(nextCount);
    if (total !== null && nextCount >= total) setFinished(true);
    else setIndex(index + 1);
  }
  function stop() {
    if (completedCount === 0) router.push('/kits');
    else setFinished(true);
  }
  function restart() { setOrder(shuffled(pool.length)); setIndex(0); setCompletedCount(0); setFinished(false); }

  return <main className="learning content-width">
    <Link className="back-button" href="/kits"><span aria-hidden="true">←</span> 뒤로가기</Link>
    <section className="session-bar">
      <div>
        <span className="eyebrow">STEP 0{stage} · {stageMeta[stage].level}</span>
        <h1>{stageNames[stage]}</h1>
        <div className="session-chips">{stage === 0 && <span>{blankModeNames[config.blankMode]}</span>}<span>{infinite ? '∞ 무한 모드' : `${total}문제`}</span></div>
      </div>
      <div className="session-progress">
        {infinite ? <><span><b>{finished ? completedCount : index + 1}</b>번째 문제</span>{!finished && <button type="button" className="button secondary" onClick={stop}>그만하기</button>}</>
          : <><span><b>{finished ? total : index + 1}</b> / {total}</span><progress max={total!} value={finished ? total! : index} aria-label="세션 진행률" /></>}
      </div>
    </section>

    {finished ? <section className="session-summary" role="status">
      <span className="summary-badge" aria-hidden="true">🎉</span>
      <span className="eyebrow">SESSION COMPLETE</span>
      <h2>{completedCount}문제를 끝냈어요, {userName}님!</h2>
      <p>학습 기록에서 피드백을 다시 확인하고 연습을 이어 가세요.</p>
      <div className="result-actions"><button type="button" className="button secondary" onClick={restart}>같은 설정으로 다시</button><Link className="button primary" href="/kits">학습 키트로 →</Link></div>
    </section>
      : <QuestionView key={index} exercise={exercise} number={index + 1} isLast={total !== null && index + 1 >= total} config={config} userName={userName} store={store} persist={persist} storageOk={storageOk} onNext={next} />}
    <DemoNote />
  </main>;
}

type QuestionProps = { exercise: Exercise; number: number; isLast: boolean; config: SessionConfig; userName: string; store: Store; persist: (next: Store) => boolean; storageOk: boolean; onNext: () => void };

function QuestionView({ exercise, number, isLast, config, userName, store, persist, storageOk, onNext }: QuestionProps) {
  const stage = exercise.stage;
  const draftKey = stage === 0 ? `${exercise.id}:${config.blankMode}` : exercise.id;
  const [draft, setDraft] = useState<Draft>(() => {
    const saved = store.drafts[draftKey];
    return saved && saved.blanks.length === (exercise.blanks || []).length ? saved : emptyDraft(exercise);
  });
  const [hint, setHint] = useState(false);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState('');
  const submitting = useRef(false);
  const resultRef = useRef<HTMLDivElement>(null);
  const filledBody = stage === 0 ? blankBody(exercise, draft.blanks) : draft.body;
  const words = filledBody.trim().split(/\s+/).filter(Boolean).length;

  useEffect(() => { if (evaluation) resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [evaluation]);

  function edit(next: Draft) {
    setDraft(next); setEvaluation(null); setNotice('');
    persist({ ...store, drafts: { ...store.drafts, [draftKey]: next } });
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting.current) return;
    if (stage === 0 && draft.blanks.some(x => !x.trim())) { setNotice('모든 빈칸을 채워 주세요.'); return; }
    submitting.current = true;
    setPending(true); setNotice(''); setEvaluation(null);
    try {
      const answer = { ...draft, body: filledBody };
      const response = await fetch(stage === 0 ? '/api/demo/evaluations' : '/api/agent/evaluations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ exerciseId: exercise.id, blankMode: config.blankMode, answer }), signal: AbortSignal.timeout(stage === 0 ? 15000 : 120000) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '채점 요청에 실패했습니다.');
      const result = data as Evaluation;
      const item: Submission = { id: crypto.randomUUID(), stage, exerciseId: exercise.id, title: exercise.title, draft: answer, evaluation: result, createdAt: new Date().toISOString() };
      const drafts = { ...store.drafts };
      delete drafts[draftKey];
      persist({ ...store, drafts, history: [item, ...store.history].slice(0, 100) });
      setEvaluation(result);
    } catch (error) {
      setNotice(error instanceof Error && error.name === 'TimeoutError' ? '응답 시간이 초과되었습니다. 작성 내용은 유지됩니다. 다시 제출해 주세요.' : error instanceof Error ? error.message : '연결을 확인하고 다시 제출해 주세요.');
    } finally { submitting.current = false; setPending(false); }
  }

  return <div className="exercise-grid">
    <section className="task-pane"><div className="pane-heading"><span>☷ &nbsp; 학습 과제</span><small>QUESTION {String(number).padStart(2, '0')}</small></div><div className="task-content"><div className="task-tags"><span>STEP {stage} · {stageMeta[stage].level}</span><span>{exercise.tag}</span></div><h2>{exercise.title}</h2><p className="task-description">{exercise.description}</p><div className="scenario"><span className="eyebrow">{stage === 2 ? 'YOUR MISSION' : 'BACKGROUND'}</span><p>{exercise.scenario}</p></div>{stage === 1 && exercise.original && <div className="original-email"><div className="document-label">ORIGINAL EMAIL · 기본 영어 메일</div><div className="document-content"><strong>Subject: {exercise.subject}</strong><p>{exercise.original}</p></div></div>}<h3>이번 문제에서 꼭 확인해 주세요</h3><ul className="requirements">{exercise.requirements.map(x => <li key={x}><span>✓</span>{x}</li>)}</ul><details className="reference"><summary>▤ &nbsp; 참고할 사내 문서 <small>예시 자료 · 1건</small></summary><p>{exercise.reference}</p><small>학습용 가상 자료입니다. 실제 사내 문서를 검색한 결과가 아닙니다.</small></details></div></section>
    <section className="writing-pane"><div className="pane-heading"><span>✎ &nbsp; {stage === 0 ? '빈칸을 채워 완성하기' : '나의 이메일'}</span><small>{stage === 0 ? 'FILL IN THE BLANKS' : 'ENGLISH WRITING'}</small></div>
      <form onSubmit={submit}><fieldset disabled={pending}>
        <div className="editor">
          <div className="recipient"><span>To</span><b>{exercise.recipient}</b></div>
          <div className="subject-row"><label htmlFor="subject">Subject</label><input id="subject" value={draft.subject} onChange={e => edit({ ...draft, subject: e.target.value })} readOnly={stage === 0} required maxLength={200} placeholder="메일의 목적이 드러나는 제목을 작성해 주세요" /></div>
          {stage === 0 ? <BlankEditor exercise={exercise} mode={config.blankMode} values={draft.blanks} onChange={blanks => edit({ ...draft, blanks })} disabled={pending || !!evaluation} results={evaluation?.checks.map(c => c.passed)} />
            : <textarea aria-label="이메일 본문" required maxLength={10000} value={draft.body} onChange={e => edit({ ...draft, body: e.target.value })} placeholder={`${exercise.recipient.startsWith('Jamie') || exercise.recipient.startsWith('Mina') ? 'Dear' : 'Hi'} ${exercise.recipient.split(' ')[0]},\n\n첫 문장을 적어보세요. 완벽하지 않아도 괜찮아요.\n\nBest regards,\n${userName}`} />}
          <div className="editor-status"><span>{storageOk ? '✓ 이 브라우저에 자동 저장' : '브라우저 저장 불가 · 현재 화면에서만 유지'}</span><span>{stage === 0 ? `${draft.blanks.filter(x => x.trim()).length} / ${draft.blanks.length} 완료` : `${words} words`}</span></div>
        </div>
        {evaluation && <div ref={resultRef} className="feedback-panel" role="status"><div className="feedback-heading"><div><span className="eyebrow">YOUR FEEDBACK</span><h3>{userName}님, 피드백을 확인해 보세요.</h3></div></div><p>{evaluation.summary}</p>{evaluation.scores.map(s => s.comment && <p className="feedback-tip" key={s.label}>{s.comment}</p>)}<ul className="feedback-checks">{evaluation.checks.map(c => <li key={c.label} className={c.passed ? 'passed' : ''}><span>{c.passed ? '✓' : '○'}</span>{c.label}</li>)}</ul>{evaluation.feedback.map(x => <p className="feedback-tip" key={x}>{x}</p>)}<small className="demo-disclaimer">{evaluation.mode === 'live' ? 'AI가 평가한 피드백입니다. 필수 요구사항과 수정 안내를 확인하세요.' : evaluation.mode === 'replay' ? 'Replay 예시 결과입니다. 실제 AI 채점이 아닙니다.' : '빈칸 정답과 해설을 확인하세요.'}</small></div>}
        <div className="editor-actions">
          <button type="button" className="button secondary hint-toggle" aria-expanded={hint} onClick={() => setHint(!hint)}>✧ &nbsp; 표현 힌트</button>
          {evaluation ? <div className="action-group"><button type="button" className="button secondary" onClick={() => { setEvaluation(null); if (stage !== 0) document.getElementById('subject')?.focus(); }}>다시 풀기</button><button type="button" className="button primary" onClick={onNext}>{isLast ? '결과 보기 →' : '다음 문제 →'}</button></div>
            : <button className="button primary">{pending ? '답안을 확인하고 있어요…' : stage === 0 ? '정답 확인하기 →' : '제출하고 피드백 보기 →'}</button>}
        </div>
      </fieldset></form>
      {hint && <div className="hint-box"><strong>이렇게 시작해 보세요</strong><p>{exercise.hint}</p></div>}
      {notice && <div className="error-note" role="alert">{notice}</div>}
      {!evaluation && <div className="editor-bottom-note">{stage === 0 ? (config.blankMode === 'choice' ? '빈칸을 누르면 보기가 나타나요.' : '빈칸에 알맞은 표현을 직접 입력하세요. 대소문자는 구분하지 않아요.') : '작성한 메일은 실제 발송되지 않아요. 안심하고 연습하세요.'}</div>}
    </section>
  </div>;
}
