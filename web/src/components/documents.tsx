'use client';

import Link from 'next/link';
import { useEffect, useRef, useState, type DragEvent } from 'react';

type DocStatus = 'ready' | 'processing';
type Doc = { id: string; name: string; category: string; size: number; uploadedAt: string; status: DocStatus; sample?: boolean };

const accepted = ['pdf', 'docx', 'txt', 'md'];
const maxSize = 20 * 1024 * 1024;
const samples: Doc[] = [
  { id: 'sample-1', name: '비즈니스 이메일 작성 가이드.pdf', category: '이메일 가이드', size: 1_240_000, uploadedAt: '2026-10-14T09:00:00+09:00', status: 'ready', sample: true },
  { id: 'sample-2', name: '고객 커뮤니케이션 매뉴얼.docx', category: '고객 응대', size: 860_000, uploadedAt: '2026-10-16T09:00:00+09:00', status: 'ready', sample: true },
  { id: 'sample-3', name: '영업팀 자료 요청 예시.md', category: '사내 예시', size: 24_000, uploadedAt: '2026-10-20T09:00:00+09:00', status: 'ready', sample: true },
];
const docsKey = (userId: string) => `rootkit-docs-v1:${userId}`;
const extension = (name: string) => name.split('.').pop()?.toLowerCase() || '';
const formatSize = (size: number) => size >= 1024 * 1024 ? `${(size / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(size / 1024))}KB`;

function readDocs(key: string): Doc[] {
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null');
    if (!Array.isArray(value)) return samples;
    return value.filter((d: Doc) => d && typeof d.id === 'string' && typeof d.name === 'string' && typeof d.size === 'number').map((d: Doc) => ({ ...d, status: 'ready' as const }));
  } catch { return samples; }
}

export default function Documents({ userId }: { userId: string }) {
  const key = docsKey(userId);
  const [docs, setDocs] = useState<Doc[]>(() => readDocs(key));
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const timers = useRef<number[]>([]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  function save(next: Doc[]) {
    setDocs(next);
    try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* 저장 실패 시 현재 화면에서만 유지 */ }
  }
  function add(files: FileList | null) {
    if (!files?.length) return;
    const valid: Doc[] = [];
    const rejected: string[] = [];
    for (const file of Array.from(files)) {
      if (!accepted.includes(extension(file.name)) || file.size > maxSize) { rejected.push(file.name); continue; }
      valid.push({ id: crypto.randomUUID(), name: file.name, category: '업로드 자료', size: file.size, uploadedAt: new Date().toISOString(), status: 'processing' });
    }
    setNotice(rejected.length ? `${rejected.join(', ')} — PDF, DOCX, TXT, MD 파일만 20MB까지 올릴 수 있어요.` : '');
    if (!valid.length) return;
    const next = [...valid, ...docs];
    save(next);
    // 데모: 학습 반영(인덱싱)을 흉내 낸다.
    timers.current.push(window.setTimeout(() => setDocs(current => {
      const done = current.map(d => valid.some(v => v.id === d.id) ? { ...d, status: 'ready' as const } : d);
      try { localStorage.setItem(key, JSON.stringify(done)); } catch { /* noop */ }
      return done;
    }), 2200));
  }
  function remove(id: string) { save(docs.filter(d => d.id !== id)); }
  function onDrop(event: DragEvent) { event.preventDefault(); setDragging(false); add(event.dataTransfer.files); }

  const readyCount = docs.filter(d => d.status === 'ready').length;

  return <main className="documents content-width">
    <div className="breadcrumb"><Link href="/kits">워크스페이스</Link> &nbsp; / &nbsp; 사내 자료 관리</div>
    <div className="dashboard-heading">
      <div><span className="eyebrow">KNOWLEDGE BASE</span><h1>사내 온보딩 자료</h1><p>이 화면은 파일 목록을 관리하는 데모입니다. 실제 학습에는 별도로 등록·검토한 회사 자료를 사용합니다.</p></div>
      <button type="button" className="button primary" onClick={() => inputRef.current?.click()}>＋ 자료 올리기</button>
    </div>

    <label className={`dropzone ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
      <input ref={inputRef} type="file" multiple accept=".pdf,.docx,.txt,.md" onChange={e => { add(e.target.files); e.target.value = ''; }} />
      <span className="dropzone-icon" aria-hidden="true">⇪</span>
      <strong>파일을 끌어다 놓거나 클릭해서 올리세요</strong>
      <small>PDF · DOCX · TXT · MD &nbsp;·&nbsp; 파일당 최대 20MB</small>
    </label>
    {notice && <div className="error-note doc-notice" role="alert">{notice}</div>}

    <div className="section-heading"><h2>등록된 자료 <span>{docs.length}</span></h2><small>데모 목록 등록 {readyCount}건</small></div>
    {docs.length === 0 ? <div className="empty-state"><span>▤</span><h2>아직 등록된 자료가 없어요.</h2><p>첫 사내 문서를 올려 보세요.</p></div>
      : <ul className="doc-list">{docs.map(doc => <li key={doc.id} className="doc-item">
        <span className={`doc-icon ext-${extension(doc.name)}`} aria-hidden="true">{extension(doc.name).toUpperCase()}</span>
        <div className="doc-main"><strong>{doc.name}</strong><span>{doc.category} · {formatSize(doc.size)} · {new Date(doc.uploadedAt).toLocaleDateString('ko-KR')}</span></div>
        <span className={`doc-status ${doc.status}`}>{doc.status === 'ready' ? '데모 목록 등록' : '처리 중…'}</span>
        <button type="button" className="doc-delete" aria-label={`${doc.name} 삭제`} onClick={() => remove(doc.id)}>✕</button>
      </li>)}</ul>}
    <footer className="demo-note"><span>ⓘ 데모 화면 · 파일은 서버로 전송되지 않고 목록만 이 브라우저에 저장됩니다. STEP 1·2 학습에는 담당자가 별도로 등록하고 검토한 데이터셋을 사용합니다.</span></footer>
  </main>;
}
