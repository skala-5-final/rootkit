'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState, type FormEvent } from 'react';
import { exercisePool, isStage, stageMeta, stageNames, type Draft, type SessionConfig, type Stage, type Submission } from '@/lib/learning';
import Documents from './documents';
import LearnSession from './learn-session';
import StartModal from './start-modal';
import RagLearnSession from './rag-learn-session';
import RagHistory from './rag-history';
import { parseRagHistory } from '@/lib/rag-contract';
import { ragFetch } from '@/lib/rag-browser';

type Screen = 'welcome' | 'login' | 'kits' | 'learn' | 'history' | 'documents';
export type User = { userId: string; loginId: string; name: string };
export type Store = { drafts: Record<string, Draft>; history: Submission[] };

const stages: Stage[] = [0, 1, 2];
const storeKey = (userId: string) => `rootkit-demo-v1:${userId}`;
const freshStore = (): Store => ({ drafts: {}, history: [] });
const navItems: { href: string; label: string; screens: Screen[] }[] = [
  { href: '/', label: '서비스 소개', screens: ['welcome'] },
  { href: '/documents', label: '사내 자료 관리', screens: ['documents'] },
  { href: '/kits', label: '학습 키트', screens: ['kits', 'learn'] },
  { href: '/history', label: '나의 학습 기록', screens: ['history'] },
];

function isDraft(value: unknown): value is Draft {
  if (!value || typeof value !== 'object') return false;
  const d = value as Draft;
  return typeof d.subject === 'string' && typeof d.body === 'string' && Array.isArray(d.blanks) && d.blanks.every(x => typeof x === 'string');
}
function readStore(key: string): Store {
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null');
    if (!value || typeof value !== 'object') return freshStore();
    const drafts: Store['drafts'] = {};
    for (const [id, draft] of Object.entries(value.drafts || {})) if (isDraft(draft)) drafts[id] = draft;
    const history = Array.isArray(value.history) ? value.history.filter((x: Submission) => x && typeof x.id === 'string' && isStage(x.stage) && isDraft(x.draft) && typeof x.createdAt === 'string' && x.evaluation && typeof x.evaluation.total === 'number' && Array.isArray(x.evaluation.scores) && Array.isArray(x.evaluation.checks) && Array.isArray(x.evaluation.feedback)) : [];
    return { drafts, history: history.slice(0, 100) };
  } catch { return freshStore(); }
}
function Brand() { return <Link className="brand" href="/" aria-label="rootkit 홈">rootkit<span className="brand-dot">.</span></Link>; }
function Arrow() { return <span aria-hidden="true">↗</span>; }

export default function Rootkit({ screen, stage = 0, config, resumeAttemptId }: { screen: Screen; stage?: Stage; config?: SessionConfig; resumeAttemptId?: string }) {
  const router = useRouter();
  const [store, setStore] = useState<Store>(freshStore);
  const [ragCompleted, setRagCompleted] = useState<number[]>([]);
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [loginId, setLoginId] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');
  const [loggingIn, setLoggingIn] = useState(false);
  const [starting, setStarting] = useState<Stage | null>(null);
  const [storageOk, setStorageOk] = useState(true);
  const [notice, setNotice] = useState('');
  const workspace = ['kits', 'learn', 'history', 'documents'].includes(screen);
  const name = user?.name || '루키';

  useEffect(() => {
    if (screen === 'login') return;
    let active = true;
    fetch('/api/auth/me').then(async response => {
      if (!active) return;
      if (!response.ok) { if (workspace) router.replace('/login'); return; }
      const { user: me } = await response.json() as { user: User };
      setUser(me); setStore(readStore(storeKey(me.userId))); setReady(true);
    }).catch(() => { if (active) setNotice('사용자 정보를 불러오지 못했습니다. 새로고침해 주세요.'); });
    return () => { active = false; };
  }, [screen, workspace, router]);

  useEffect(() => {
    if (screen !== 'kits' || !user) return;
    let active = true;
    ragFetch('/api/rag/history', parseRagHistory).then(result => {
      if (active) setRagCompleted([...new Set(result.items.filter(item => item.submissions.length > 0).map(item => item.exercise.stage))]);
    }).catch(() => { /* The learning screen reports service errors; STEP 0 stays available. */ });
    return () => { active = false; };
  }, [screen, user]);

  function persist(next: Store) {
    setStore(next);
    if (!user) return false;
    try { localStorage.setItem(storeKey(user.userId), JSON.stringify(next)); setStorageOk(true); return true; }
    catch { setStorageOk(false); return false; }
  }
  async function login(event: FormEvent) {
    event.preventDefault();
    setLoggingIn(true); setLoginError('');
    try {
      const response = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ loginId, password }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '로그인에 실패했습니다.');
      router.push('/kits');
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : '연결을 확인하고 다시 시도해 주세요.');
      setLoggingIn(false);
    }
  }
  async function logout() {
    await fetch('/api/auth/logout', { method: 'POST' }).catch(() => null);
    router.push('/login');
  }
  function start(s: Stage, next: SessionConfig) {
    setStarting(null);
    router.push(`/learn/${s}?count=${next.count}${s === 0 ? `&type=${next.blankMode}` : ''}`);
  }
  const completed = stages.filter(s => store.history.some(h => h.stage === s) || ragCompleted.includes(s));

  return <div className={`app ${workspace ? 'workspace' : screen === 'welcome' ? 'landing' : ''}`}>
    <header className="site-header">
      <div className="header-start">
        <Brand />
        {screen !== 'login' && <nav className="main-nav" aria-label="주 메뉴">{navItems.map(item => <Link key={item.href} href={item.href} className={item.screens.includes(screen) ? 'active' : ''} aria-current={item.screens.includes(screen) ? 'page' : undefined}>{item.label}</Link>)}</nav>}
      </div>
      <div className="header-end">
        {user ? <><span className="badge header-badge">🌱 신입사원 과정</span><span className="avatar">{name.slice(0, 1)}</span><span className="user-name">{name}님</span><button className="text-button" onClick={logout}>나가기</button></>
          : screen === 'login' ? <Link className="text-button" href="/">← 처음으로</Link>
          : <Link className="button primary header-login" href="/login">로그인</Link>}
      </div>
    </header>

    {screen === 'welcome' && <>
      <section className="hero-field"><main className="hero"><div className="hero-copy"><span className="eyebrow">YOUR FIRST STEP AT WORK</span><h1>첫 업무 메일도,<br /><em>자신 있게 보내도록.</em></h1><p>우리 회사의 언어를 배우는 가장 좋은 시작.{' '}<br />실제 업무 문서로 연습하며, 나만의 비즈니스 영어를 완성하세요.</p><Link className="button primary hero-cta" href={user ? '/kits' : '/login'}>나의 첫 연습 시작하기 <Arrow /></Link><span className="fine-print">신입사원을 위한 실무 학습 키트, rootkit</span></div><div className="hero-art" aria-label="기본 영어 표현을 비즈니스 표현으로 개선한 예시"><span className="spark">✳</span><div className="floating-mail"><div className="mail-top"><span className="mail-icon">✉</span><span className="badge">A little more professional</span></div><div className="skeleton-line short" /><div className="skeleton-line" /><p className="before-line">Send me the report by Friday.</p><div className="after-line">Could you please share the report<br />by Friday?<small>명확한 요청에 정중함을 더해보세요.</small></div></div><span className="floating-note"><b>✓</b> 작은 연습이, 실무의 자신감으로.</span></div></main></section>
      <section className="intro-steps" aria-label="학습 과정">{stages.map(s => <article key={s}><span className="step-number">0{s} /</span><div><h2>{stageNames[s]}</h2><p>{['빈칸을 채우며 실무에서 쓰는\n핵심 표현부터 익혀요.', '기본 이메일을 다듬으며\n정중한 문장을 연습해요.', '업무 상황을 읽고\n나만의 이메일을 완성해요.'][s]}</p></div></article>)}</section><footer className="landing-footer"><span>우리 회사 문서로 배우는 첫 실무</span><span>ROOKIE TODAY. READY TOMORROW.</span></footer>
    </>}

    {screen === 'login' && <main className="login-layout"><section className="login-story"><span className="eyebrow">WELCOME TO YOUR NEXT CHAPTER</span><h1>처음이라 낯선 업무,<br />연습하면 익숙해집니다.</h1><p>하나의 메일, 하나의 표현부터.<br />rootkit과 함께 첫 업무를 준비해 보세요.</p><div className="login-quote"><span>“Could you please…?”</span><p>작은 표현의 차이가 만드는,<br />더 좋은 커뮤니케이션.</p><small>BUSINESS ENGLISH · ROOTKIT</small></div></section><section className="login-form-wrap"><form onSubmit={login} className="login-form"><span className="badge">나의 온보딩 워크스페이스</span><h2>반가워요, 루키님 <span>👋</span></h2><p>회사 계정으로 학습을 시작하세요.</p><fieldset disabled={loggingIn}><label htmlFor="loginId">아이디</label><input id="loginId" value={loginId} maxLength={50} onChange={e => setLoginId(e.target.value)} placeholder="아이디를 입력하세요" autoComplete="username" required /><label htmlFor="password">비밀번호</label><input id="password" type="password" value={password} maxLength={200} onChange={e => setPassword(e.target.value)} placeholder="비밀번호를 입력하세요" autoComplete="current-password" required /><button className="button primary">{loggingIn ? '로그인 중…' : '로그인'} <span>→</span></button></fieldset>{loginError && <div className="error-note" role="alert">{loginError}</div>}<div className="info-note">계정은 담당자가 발급합니다.<br />초안과 STEP 0 데모 기록은 이 브라우저에,<br />STEP 1·2 제출 기록은 서버에 저장됩니다.</div></form></section></main>}

    {screen === 'kits' && <main className="dashboard content-width"><div className="breadcrumb">워크스페이스 &nbsp; / &nbsp; 온보딩 학습 키트</div><div className="dashboard-heading"><div><span className="eyebrow">YOUR LEARNING JOURNEY</span><h1>{name}님, 오늘도 한 걸음 더.</h1><p>빈칸 채우기부터 직접 작성까지. 나의 속도로 차근차근 연습하세요.</p></div><span className="badge">BUSINESS ENGLISH</span></div><section className="progress-banner"><div><span className="progress-icon">↗</span><div><h2>비즈니스 이메일 첫걸음</h2><p>동료에게 자료를 요청하고, 고객에게 일정을 안내하는 법을 배워요.</p></div></div><div className="progress-summary"><span><b>{completed.length}</b> / 3 단계 제출</span><progress max={3} value={completed.length} aria-label="학습 진행률" /></div></section><div className="section-heading"><h2>나의 학습 키트 <span>03</span></h2><small>순서대로, 또는 원하는 단계부터 시작하세요.</small></div><section className="kit-grid">{stages.map(s => {
      const done = completed.includes(s);
      return <article className="kit-card" key={s}><div className={`kit-art art-${s}`} aria-hidden="true">{s === 0 ? <div className="art-paper"><span>Could you <i>please</i></span><span>share the report?</span><b>✧</b></div> : s === 1 ? <div className="art-paper"><del>Send me the report.</del><span className="art-highlight">Could you please…?</span><b>✎</b></div> : <div className="art-paper"><span>To: Jamie Lee</span><span>Subject: <i>My first email</i></span><b>↗</b></div>}</div><div className="kit-card-content"><div className="card-meta"><span>STEP 0{s} · {stageMeta[s].level}</span><span>{done ? '✓ 제출 완료' : '시작 전'}</span></div><h3>{stageNames[s]}</h3><p>{stageMeta[s].subtitle}</p><div className="kit-info"><span>{s === 0 ? `✉ 데모 문제 ${exercisePool[0].length}종` : '✉ 검토 통과한 활성 문제집'}</span><span>◷ 문제당 약 {stageMeta[s].minutes}분</span></div><button type="button" className={`button ${s === 0 ? 'primary' : 'secondary'}`} onClick={() => setStarting(s)}>{done ? '다시 연습하기' : '연습 시작하기'} <span>→</span></button></div></article>;
    })}</section><div className="learning-tip"><span>✧</span><div><strong>완벽한 문장보다, 직접 써보는 경험이 먼저예요.</strong><p>작성한 이메일은 피드백을 확인하고 언제든 수정해 다시 제출할 수 있어요.</p></div><Link href="/history">학습 기록 보기 →</Link></div><footer className="demo-note"><span>STEP 0은 데모 · STEP 1·2는 검토를 통과한 회사 문서 기반 문제로 연습합니다.</span></footer>{starting !== null && <StartModal stage={starting} onClose={() => setStarting(null)} onStart={next => start(starting, next)} />}</main>}

    {screen === 'learn' && config && (ready && user ? (stage === 0 ? <LearnSession key={`${stage}-${config.count}-${config.blankMode}`} stage={stage} config={config} userName={name} store={store} persist={persist} storageOk={storageOk} /> : <RagLearnSession key={`${stage}-${config.count}`} stage={stage} config={config} userId={user.userId} resumeAttemptId={resumeAttemptId} />) : <main className="content-width"><p className="empty-state" role="status">학습 키트를 준비하고 있어요…</p></main>)}

    {screen === 'history' && <main className="history content-width"><div className="breadcrumb"><Link href="/kits">워크스페이스</Link> &nbsp; / &nbsp; 나의 학습 기록</div><div className="dashboard-heading"><div><span className="eyebrow">EVERY SMALL STEP COUNTS</span><h1>차곡차곡 쌓이는 나의 연습</h1><p>작성한 답안과 피드백을 돌아보며, 다음 문장을 더 자신 있게.</p></div><Link href="/kits" className="button primary">연습하러 가기 →</Link></div>{ready && user && <RagHistory userId={user.userId} />}<div className="section-heading"><h2>이 브라우저의 데모 기록</h2><small>기존 기록 유지</small></div><div className="history-stats"><div><span>데모 제출 답안</span><b>{store.history.length}<small>개</small></b></div><div><span>연습한 단계</span><b>{completed.length}<small> / 3</small></b></div><div><span>최근 데모 점수</span><b>{store.history[0]?.evaluation.total ?? '—'}<small> / 100</small></b></div></div>{!ready ? <p className="empty-state">학습 기록을 불러오고 있어요.</p> : store.history.length === 0 ? <div className="empty-state"><span>✉</span><h2>아직 첫 문장을 기다리고 있어요.</h2><p>빈칸 채우기부터 가볍게 시작해 보세요.</p><Link className="button primary" href="/kits">첫 연습 시작하기 →</Link></div> : <div className="history-list">{store.history.map(item => <details className="history-item" key={item.id}><summary><span className="history-step">0{item.stage}</span><div><strong>{item.title || stageNames[item.stage]}</strong><span>{new Date(item.createdAt).toLocaleString('ko-KR')} · {stageNames[item.stage]} · {item.draft.subject}</span></div><b>{item.evaluation.total}<small>점</small></b><span aria-hidden="true">⌄</span></summary><div className="history-detail"><div><h3>제출한 이메일</h3><strong>{item.draft.subject}</strong><p>{item.draft.body || item.draft.blanks.join(' / ')}</p></div><div><h3>데모 피드백</h3><p>{item.evaluation.summary}</p>{item.evaluation.checks.map(c => <p key={c.label}>{c.passed ? '✓' : '○'} {c.label}</p>)}{item.evaluation.feedback.map(f => <p key={f}>{f}</p>)}<Link href="/kits" className="button secondary">다시 연습하기 →</Link></div></div></details>)}</div>}<DemoNote /></main>}

    {screen === 'documents' && (user ? <Documents userId={user.userId} /> : <main className="content-width"><p className="empty-state" role="status">자료 목록을 불러오고 있어요…</p></main>)}

    {notice && <div className="storage-warning" role="alert">{notice}</div>}
    {!storageOk && <div className="storage-warning" role="status">브라우저 저장을 사용할 수 없어 새로고침하면 기록이 사라질 수 있어요.</div>}
  </div>;
}
export function DemoNote() { return <footer className="demo-note"><span>ⓘ 데모 모드 · 가상 문제와 규칙 기반 피드백 · 기록은 현재 브라우저에 저장됩니다.</span><span>ROOKIE TODAY. READY TOMORROW.</span></footer>; }
