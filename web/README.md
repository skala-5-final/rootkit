# rootkit Next.js

2026-10-23 현재 STEP 0은 기존 데모이며, STEP 1·2는 회사 문서에서 생성하고 별도 AI 검토를 통과한 활성 문제집을 사용합니다. 로그인은 서버 계정과 JWT 쿠키로 확인하고, RAG 제출 답안과 피드백은 AI 서버에 저장합니다. 초안과 기존 데모 기록은 사용자별 브라우저 저장소에 유지합니다.

현재 실행·데이터 등록·문제집 교체 방법은 [저장소 README](../README.md), [RAG 운영 안내](../docs/rag-feedback.md), [API 계약](../docs/rag-api-contract.md)을 참고하세요. 웹 회귀 테스트는 `pnpm test:rag`로 실행합니다.

아래 내용은 초기 데모 구현 당시의 기록입니다. 현재 인증·저장 위치·STEP 1·2 동작과 실행 방법은 위 문서를 기준으로 확인하세요.

## 초기 데모 구현 기록

기존 HTML 예시를 App Router와 React로 옮긴 온보딩 학습 프로토타입입니다.

## 실행

```bash
pnpm install
pnpm dev
# http://localhost:3000
```

이 데모 화면은 PostgreSQL이나 FastAPI 없이 실행됩니다. 기존 DB 연결과 헬스체크는 유지되어 있으며 `/api/health`는 DB 설정이 필요합니다.

## 화면

| 경로 | 기능 |
| --- | --- |
| `/` | 스플래시 / 서비스 소개 |
| `/login` | 닉네임으로 시작하는 데모 진입 화면 |
| `/kits` | 3단계 키트 목록, 진행률, 이어서 학습 |
| `/learn/0` | 메일의 빈칸 3곳에 표현 선택, 정답 확인 |
| `/learn/1` | 기본 이메일을 다듬어 제목·본문 제출 |
| `/learn/2` | 업무 상황을 읽고 이메일 직접 작성 |
| `/history` | 제출별 답안·점수·피드백, 다시 연습 |

닉네임·단계별 초안·최근 100개 제출 기록은 브라우저 localStorage의 `rootkit-demo-v1` 키에 저장합니다. 실제 회원 인증 및 사용자별 서버 저장은 연결하지 않았습니다. 공유 브라우저에서는 같은 데모 기록을 보게 됩니다. `나가기`는 닉네임만 초기화하며 연습 기록은 유지합니다.

## 데모 채점 API

`POST /api/demo/evaluations`

```json
{
  "stage": 0,
  "answer": {
    "subject": "Request for this month's sales report",
    "body": "",
    "blanks": ["Could you please", "by", "Please let me know"]
  }
}
```

- `stage`: `0 | 1 | 2`.
- 0단계: 세 빈칸의 선택지를 검증하고 서버에 있는 정답과 비교합니다.
- 1·2단계: 제목·본문 필수, 제목 200자·본문 10,000자 제한. 키워드·구성·정중한 표현·분량으로 데모 점수를 계산합니다. 의미나 문법을 평가하는 AI가 아닙니다.
- 성공 시 `Evaluation` 형식, 유효하지 않은 입력은 422, 잘못된 JSON은 400을 반환합니다.
- 구현: `src/lib/learning.ts`(문제와 타입), `src/lib/demo-evaluation.ts`(서버 전용 채점), `src/app/api/demo/evaluations/route.ts`(요청 검증).
- 실제 AI 연동 시 사용자용 API 및 서버 저장을 구현하고 FastAPI로 평가를 위임해야 합니다. 현재 데모 엔드포인트는 인증을 요구하지 않습니다.

## DB 변경

`exercises.stage`의 CHECK 제약에 0단계를 추가했습니다. 생성한 증분 마이그레이션은 `drizzle/0001_secret_hobgoblin.sql`입니다.

```bash
pnpm db:migrate
```

마이그레이션은 DB가 준비된 환경에서 적용하세요. 현재 데모 답안은 이 DB에 기록되지 않습니다. 0단계 서버 저장 시 `submissions.body`에는 완성된 메일을, `evaluationJson`에는 선택 항목과 평가를 저장하도록 확장할 수 있습니다.

## 확인

```bash
pnpm exec tsc --noEmit
pnpm build
```
