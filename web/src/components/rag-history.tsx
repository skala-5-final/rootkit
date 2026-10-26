'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ragError, ragFetch, saveRagDraft } from '@/lib/rag-browser';
import { parseRagHistory, type RagHistoryItem } from '@/lib/rag-contract';
import RagFeedback, { ragStatus } from './rag-feedback';

export default function RagHistory({ userId }: { userId: string }) {
  const [items, setItems] = useState<RagHistoryItem[] | null>(null);
  const [notice, setNotice] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    ragFetch('/api/rag/history', parseRagHistory)
      .then(result => { if (active) { setItems(result.items); setNotice(''); } })
      .catch(error => { if (active) setNotice(ragError(error)); });
    return () => { active = false; };
  }, [reload]);
  return <section className="rag-history" aria-labelledby="rag-history-title">
    <div className="section-heading"><h2 id="rag-history-title">회사 문서 기반 학습 기록</h2><small>서버 저장 · STEP 1·2</small></div>
    {notice ? <div className="error-note" role="alert">{notice} <button className="text-button" onClick={() => setReload(value => value + 1)}>다시 불러오기</button></div>
      : items === null ? <p className="empty-state" role="status">서버 기록을 불러오고 있어요…</p>
      : items.length === 0 ? <p className="empty-state">아직 회사 문서 기반으로 시작한 문제가 없습니다. 학습 키트에서 STEP 1 또는 STEP 2를 시작해 주세요.</p>
      : <div className="history-list">{items.map(item => <details className="history-item" key={item.attempt_id}>
        <summary><span className="history-step">0{item.exercise.stage}</span><div><strong>{item.exercise.title}</strong><span>{item.exercise.dataset_id} v{item.exercise.dataset_version} · 제출 {item.submissions.length}회</span></div><span>{item.submissions.length ? ragStatus[item.submissions[item.submissions.length - 1].result.status] : '작성 중'}</span></summary>
        <div className="rag-history-content"><p>{item.exercise.scenario}</p><small>문제 {item.exercise.id} v{item.exercise.version} · 근거 {item.exercise.source_ids.join(', ')}</small><p><Link className="button secondary" href={`/learn/${item.exercise.stage}?attempt=${encodeURIComponent(item.attempt_id)}`}>이 문제 이어서 풀기 →</Link></p>
          {item.submissions.slice().reverse().map(submission => <section className="rag-submission" key={submission.request_id}><h3>{new Date(submission.created_at).toLocaleString('ko-KR')} 제출</h3><strong>{submission.answer.subject}</strong><p>{submission.answer.body}</p><RagFeedback result={submission.result} /><Link className="button secondary" href={`/learn/${item.exercise.stage}?attempt=${encodeURIComponent(item.attempt_id)}`} onClick={() => saveRagDraft(userId, item.attempt_id, { answer: submission.answer, pending: { request_id: submission.request_id, answer: submission.answer } })}>이 답안을 수정·재제출하기 →</Link></section>)}
        </div>
      </details>)}</div>}
  </section>;
}
