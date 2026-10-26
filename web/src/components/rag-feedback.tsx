import type { RagEvaluation } from '@/lib/rag-contract';

export const ragStatus = { match: '요구사항 충족', needs_revision: '수정 필요', insufficient_evidence: '판단 보류 · 검토 확인 필요' } as const;
const categoryNames = { company: '회사 문서 근거', task: '이번 문제 조건', general: '일반 조언' } as const;

export default function RagFeedback({ result }: { result: RagEvaluation }) {
  return <div className="feedback-panel rag-feedback" role="status">
    <div className="feedback-heading"><div><span className="eyebrow">YOUR FEEDBACK</span><h3>{ragStatus[result.status]}</h3></div></div>
    <p>{result.summary}</p>
    {result.feedback.map((feedback, index) => <div className="feedback-tip" key={`${feedback.criterion_id}-${index}`}>
      <span className="badge">{categoryNames[feedback.category]}</span>
      <p>{feedback.explanation}</p>
      {feedback.suggestion && <><strong>수정 방향·예시</strong><p>{feedback.suggestion}</p></>}
      {feedback.evidence_ids.length > 0 && <small>근거 ID: {feedback.evidence_ids.join(', ')}</small>}
    </div>)}
    <p className="demo-disclaimer">회사 문서 근거, 이번 문제의 조건, 일반 조언을 구분해 안내합니다. 피드백의 근거나 정확성을 검토에서 확인하지 못하면 판단을 보류합니다.</p>
  </div>;
}
