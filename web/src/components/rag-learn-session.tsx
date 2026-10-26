'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { stageMeta, stageNames, type SessionConfig } from '@/lib/learning';
import { activeAttemptKey, evaluateRagDraft, ragError, ragFetch, readRagDraft, saveRagDraft, type RagDraft } from '@/lib/rag-browser';
import { parseRagAttempt, type RagAnswer, type RagAttempt, type RagEvaluation, type RagStage } from '@/lib/rag-contract';
import RagFeedback from './rag-feedback';

type Props = { stage: RagStage; config: SessionConfig; userId: string; resumeAttemptId?: string };

export default function RagLearnSession({ stage, config, userId, resumeAttemptId }: Props) {
  const [attempt, setAttempt] = useState<RagAttempt | null>(null);
  const [draft, setDraft] = useState<RagDraft>({ answer: { subject: '', body: '' }, pending: null });
  const [evaluation, setEvaluation] = useState<RagEvaluation | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState('');
  const [storageOk, setStorageOk] = useState(true);
  const [completed, setCompleted] = useState(0);
  const [finished, setFinished] = useState(false);
  const busy = useRef(false);
  const resultRef = useRef<HTMLDivElement>(null);
  const loadNumber = useRef(0);
  const pendingLoad = useRef<{ key: string; promise: Promise<RagAttempt> } | null>(null);
  const total = config.count === 'infinite' ? null : config.count;

  const loadAttempt = useCallback(async (fresh: boolean) => {
    const current = ++loadNumber.current;
    try {
      let savedId = fresh ? undefined : resumeAttemptId;
      if (!fresh && !savedId) {
        try { savedId = localStorage.getItem(activeAttemptKey(userId, stage)) || undefined; } catch { /* URL-based resume remains available. */ }
      }
      const key = savedId ?? `new-${stage}`;
      if (pendingLoad.current?.key !== key) {
        const promise = savedId
          ? ragFetch(`/api/rag/attempts/${encodeURIComponent(savedId)}`, parseRagAttempt)
          : ragFetch('/api/rag/attempts', parseRagAttempt, { stage });
        pendingLoad.current = { key, promise };
      }
      const pending = pendingLoad.current;
      let result: RagAttempt;
      try { result = await pending.promise; }
      finally { if (pendingLoad.current === pending) pendingLoad.current = null; }
      if (current !== loadNumber.current) return;
      if (result.exercise.stage !== stage) throw new Error('이 기록의 학습 단계가 다릅니다. 학습 기록에서 다시 열어 주세요.');
      setAttempt(result); setDraft(readRagDraft(userId, result.attempt_id)); setEvaluation(null);
      try { localStorage.setItem(activeAttemptKey(userId, stage), result.attempt_id); } catch { setStorageOk(false); }
      // The URL pins the attempt even when browser storage is unavailable.
      const url = new URL(window.location.href);
      url.searchParams.set('attempt', result.attempt_id);
      window.history.replaceState(null, '', url);
    } catch (error) { if (current === loadNumber.current) setNotice(ragError(error)); }
    finally { if (current === loadNumber.current) setLoading(false); }
  }, [resumeAttemptId, stage, userId]);

  useEffect(() => {
    let active = true;
    // Skip work for React's discarded development mount before creating a server attempt.
    void Promise.resolve().then(() => { if (active) return loadAttempt(false); });
    return () => { active = false; loadNumber.current += 1; };
  }, [loadAttempt]);
  useEffect(() => { if (evaluation) resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [evaluation]);

  function startLoad(fresh: boolean) {
    setLoading(true); setNotice('');
    void loadAttempt(fresh);
  }

  function persist(next: RagDraft) {
    setDraft(next);
    if (attempt) setStorageOk(saveRagDraft(userId, attempt.attempt_id, next));
  }
  function edit(answer: RagAnswer) {
    // Any edit invalidates the request key; a timeout without edits keeps the key.
    persist({ answer, pending: null }); setEvaluation(null); setNotice('');
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!attempt || busy.current) return;
    if (!draft.answer.subject.trim() || !draft.answer.body.trim()) { setNotice('제목과 본문을 모두 작성해 주세요.'); return; }
    busy.current = true; setSubmitting(true); setNotice('');
    try {
      const result = await evaluateRagDraft(attempt.attempt_id, draft, persist);
      setEvaluation(result);
    } catch (error) { setNotice(ragError(error)); }
    finally { busy.current = false; setSubmitting(false); }
  }
  function next() {
    const count = completed + 1;
    setCompleted(count);
    if (total !== null && count >= total) setFinished(true);
    else { setAttempt(null); startLoad(true); }
  }
  const exercise = attempt?.exercise;

  return <main className="learning content-width">
    <Link className="back-button" href="/kits">← 학습 키트로</Link>
    <section className="session-bar"><div><span className="eyebrow">STEP 0{stage} · {stageMeta[stage].level}</span><h1>{stageNames[stage]}</h1><div className="session-chips"><span>회사 문서 기반 문제</span><span>{total === null ? '∞ 무한 모드' : `${total}문제`}</span></div></div><div className="session-progress"><span>{completed}문제 완료{total !== null ? ` / ${total}` : ''}</span><Link className="button secondary" href="/history">학습 기록</Link>{!finished && <button type="button" className="text-button" disabled={loading || submitting} onClick={() => startLoad(true)}>새 문제 시작</button>}</div></section>
    {finished ? <section className="session-summary" role="status"><h2>{completed}문제를 연습했어요.</h2><p>문제별 답안과 피드백은 서버에 저장되었습니다.</p><div className="result-actions"><Link className="button primary" href="/history">피드백 돌아보기 →</Link><Link className="button secondary" href="/kits">학습 키트로</Link></div></section>
      : loading ? <p className="empty-state" role="status">문제와 평가 기준을 준비하고 있어요…</p>
      : exercise && attempt ? <div className="exercise-grid">
        <section className="task-pane"><div className="pane-heading"><span>학습 과제</span><small>QUESTION {completed + 1}</small></div><div className="task-content">
          <div className="task-tags"><span>STEP {stage}</span><span>{exercise.language}</span><span>{exercise.recipient_group === 'customer' ? '고객' : '일반 수신자'}</span></div>
          <h2>{exercise.title}</h2><div className="scenario"><span className="eyebrow">YOUR MISSION</span><p>{exercise.scenario}</p></div>
          {exercise.original && <div className="original-email"><div className="document-label">고쳐 쓸 원문</div><div className="document-content"><strong>{exercise.subject}</strong><p>{exercise.original}</p></div></div>}
          <h3>이번 문제의 요구사항</h3><ul className="requirements">{exercise.requirements.map((requirement, i) => <li key={i}><span>✓</span>{requirement}</li>)}</ul>
          <h3>유지해야 하는 사실</h3><ul className="rag-facts">{exercise.facts.map(fact => <li key={fact.id}><strong>{fact.value}</strong><small>{fact.origin === 'exercise' ? '이번 연습에서 설정한 조건' : '원문에 제시된 사실'}{fact.source_ids.length ? ` · 근거: ${fact.source_ids.join(', ')}` : ''}</small></li>)}</ul>
          <details className="reference"><summary>문제 출처·버전</summary><p>데이터셋 {exercise.dataset_id} · 버전 {exercise.dataset_version}<br />문제 {exercise.id} · 버전 {exercise.version}</p><p>원문 근거 ID: {exercise.source_ids.join(', ')}</p><small>이 문제를 시작할 때의 자료와 평가 기준을 유지합니다.</small></details>
        </div></section>
        <section className="writing-pane"><div className="pane-heading"><span>나의 이메일</span><small>{exercise.language}</small></div>
          <form onSubmit={submit}><fieldset disabled={submitting}><div className="editor"><div className="recipient"><span>To</span><b>{exercise.recipient}</b></div><div className="subject-row"><label htmlFor="rag-subject">Subject</label><input id="rag-subject" maxLength={200} required value={draft.answer.subject} onChange={e => edit({ ...draft.answer, subject: e.target.value })} placeholder="메일 제목을 작성해 주세요" /></div><textarea aria-label="이메일 본문" required maxLength={10000} value={draft.answer.body} onChange={e => edit({ ...draft.answer, body: e.target.value })} placeholder="문제의 조건을 바탕으로 메일을 작성해 주세요." /><div className="editor-status"><span>{storageOk ? '초안은 이 브라우저에 자동 저장' : '초안을 저장할 수 없습니다. 창을 닫기 전에 복사해 주세요.'}</span><span>{draft.answer.body.length}자</span></div></div>
            <div ref={resultRef}>{evaluation && <RagFeedback result={evaluation} />}</div>
            <div className="editor-actions"><button className="button primary">{submitting ? '근거를 확인하고 피드백을 검토하고 있어요…' : draft.pending ? '이전 평가 결과 확인하기' : evaluation ? '다시 평가하기' : '제출하고 피드백 보기 →'}</button>{evaluation && <button type="button" className="button secondary" onClick={next}>{total !== null && completed + 1 >= total ? '연습 마치기' : '다음 문제 →'}</button>}</div>
          </fieldset></form><p className="editor-bottom-note">메일은 실제 발송되지 않습니다. 제출한 답안과 피드백은 서버의 학습 기록에 저장됩니다.</p>
        </section>
      </div> : <section className="empty-state"><h2>문제를 불러오지 못했습니다.</h2><p>검토를 통과한 활성 문제집이 있어야 학습할 수 있습니다.</p><div className="result-actions"><button className="button secondary" onClick={() => startLoad(false)}>기존 문제 다시 불러오기</button><button className="button primary" onClick={() => startLoad(true)}>현재 문제집에서 새로 시작</button></div></section>}
    {notice && <div className="error-note" role="alert">{notice}</div>}
    <footer className="demo-note"><span>STEP 1·2 · 회사 자료에서 생성하고 별도 AI 검토를 통과한 문제 · 작성 중인 초안은 현재 브라우저에 저장됩니다.</span></footer>
  </main>;
}
