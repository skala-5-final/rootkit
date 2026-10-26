# rootkit

비즈니스 영어 이메일 온보딩 학습 서비스.

**새로운 세션은 [기획서](./docs/기획서.md)와 [RAG 운영 안내](./docs/rag-feedback.md)부터 확인하세요.** STEP 0는 기존 데모를 유지하고 STEP 1·2는 검토를 통과한 회사 데이터 기반 문제를 사용합니다. 최신 평가 계약은 [RAG API 계약](./docs/rag-api-contract.md)이며 수치 점수를 사용하지 않습니다.

## 구조

```
docs/                 설계 문서
prototype/            UI 프로토타입(정적 HTML, git 제외)
web/                  Next.js 앱 (App Router, TS, Tailwind, Drizzle ORM)
  src/db/schema.ts    DB 스키마 (users / exercises / submissions)
  drizzle/            생성된 SQL 마이그레이션
ai/                   FastAPI, JSONL 반입·생성·검토 CLI, SQLite 저장
  app/                문서·용어·문제집·시도·피드백 처리
  fixtures/           가상의 테스트 데이터셋 A/B
  tests/              모의 모델 응답을 사용하는 통합 테스트
rookit-agent/         영어 학습 에이전트(FastAPI), 영어 문제·평가 사례 데이터
docker-compose.yml    db(Postgres 17) + migrate + web + ai + agent
```

## Docker로 전부 띄우기

최초 실행 시 `web/.env`를 먼저 만드세요. 이미 파일이 있으면 복사를 생략하고 기존 설정을 유지하세요.

```bash
cp web/.env.example web/.env   # 최초 1회
cp ai/.env.example ai/.env     # 최초 1회
# 실행 전 web/.env의 JWT_SECRET을 임의의 키로 변경하세요 (아래 인증 참고).
# web/.env의 AI_API_TOKEN도 임의의 키로 변경하세요.
# ai/.env에는 실제 MODEL_API_KEY와 MODEL_NAME을 설정하세요.
docker compose up -d --build
# http://localhost:3000, 헬스체크: http://localhost:3000/api/health
```

`migrate` 서비스가 마이그레이션과 데모 계정 시드를 마친 뒤 `web`이 시작됩니다.

- 데모 계정: 아이디 `rookie` / 비밀번호 `rootkit1234` (로컬 시드 실행 시 `SEED_LOGIN_ID`, `SEED_PASSWORD`로 변경 가능)
- DB 호스트 포트는 **5433**입니다. 로컬에 설치된 Postgres(5432)와 충돌하지 않게 하기 위함입니다.
- AI API는 `127.0.0.1:8000`에서 내부 토큰 인증을 사용합니다. 모델 키·이름이 없으면 생성·평가 요청은 실패하며, 데모 결과로 대체하지 않습니다.
- 처음에는 활성 문제집이 없습니다. [등록 → 용어 승인 → 생성 → 검토 → 활성화](./docs/rag-feedback.md)를 완료한 뒤 STEP 1·2를 시작하세요.
- 기존 Docker 컨테이너는 소스 변경을 자동 반영하지 않습니다. 변경 후 위 빌드 명령을 다시 실행하세요.

## 인증

아이디/비밀번호 로그인 → JWT(HS256)를 httpOnly 쿠키 `rootkit_session`에 저장(7일).
`src/proxy.ts`가 학습 화면과 `/api/demo/*`, `/api/rag/*`를 보호합니다. 비밀번호는 scrypt로 해시합니다.
`JWT_SECRET`(32자 이상)이 필요합니다. 로컬과 Docker 모두 `web/.env`에 지정하세요. `openssl rand -base64 48`로 키를 생성한 뒤 `JWT_SECRET` 값을 교체하세요.
Docker는 `env_file: ./web/.env`로 이 파일을 읽고, `DATABASE_URL`과 `AI_API_BASE_URL`은 `docker-compose.yml`의 컨테이너용 값으로 덮어씁니다.
`AI_API_TOKEN`은 Next.js와 FastAPI 사이에 공유하는 내부 인증키입니다. `MODEL_API_KEY`와는 별개이며 브라우저로 보내지 않습니다. `ai/.env`에 같은 이름의 토큰을 덮어쓰지 마세요.

## 로컬 개발 (DB만 Docker)

```bash
cp web/.env.example web/.env   # 최초 1회. 기존 파일이 있으면 생략
# web/.env의 JWT_SECRET 설정 후 실행
docker compose up -d db
cd web
pnpm install
pnpm db:migrate
pnpm db:seed      # 데모 계정 생성
pnpm dev
```

로컬 FastAPI 실행과 데이터 관리 명령은 [RAG 운영 안내](./docs/rag-feedback.md)에 있습니다. 웹만 실행했거나 문제집을 활성화하지 않았다면 STEP 1·2에 오류/준비 상태가 표시됩니다.

## 저장 위치와 검토 책임

- PostgreSQL `pgdata`: 기존 사용자·인증 데이터. 기존 테이블과 STEP 0 코드는 유지합니다.
- SQLite `ai-data` 볼륨의 `/data/rootkit.sqlite3`: 문서 원문, 데이터 버전, 용어·구성 패턴, 문제·기준, 검토 사유, 시도 스냅샷, 제출·결과. 로컬 기본 경로는 `ai/data/rootkit.sqlite3`입니다.
- 브라우저 저장소: STEP 0 기록과 초안. 사내 자료 관리 화면의 파일 선택기는 여전히 목록 데모이며 CLI 반입을 대신하지 않습니다.

공식 용어와 허용 별칭은 사람이 승인합니다. 문제·기준 생성과 별도 AI 검토는 자동화하며, 사람은 통과 표본과 실패·불일치 항목을 검토합니다. AI 검토는 품질 보증이나 정확도 수치가 아닙니다.

## 테스트

```bash
cd ai
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -t . -v
cd ../web
pnpm install --frozen-lockfile
pnpm test:rag
pnpm exec tsc --noEmit
pnpm lint
pnpm build
```

Python 테스트는 가상의 A/B 문서와 **테스트 전용 모의 모델**을 사용합니다. 실제 AI의 한국어 평가 정확도를 검증하는 테스트가 아닙니다. 현재 실행 결과와 제한사항은 [검증 기록](./docs/rag-verification.md)을 참고하세요.

## 스키마 변경

```bash
cd web
# src/db/schema.ts 수정 후
pnpm db:generate   # drizzle/ 에 SQL 생성 (커밋 대상)
pnpm db:migrate
pnpm db:studio     # DB 브라우저
```

## 학습 언어 선택 (한국어 · 영어)

학습 키트 화면 상단에서 언어를 고른다. 선택은 이 브라우저에 저장된다. STEP 0은 언어와 관계없이 기존 데모를 사용한다.

- 한국어: STEP 1·2가 `ai` 서비스(RAG, 검토를 통과한 활성 문제집)를 사용한다. 기록은 서버에 저장된다.
- 영어: STEP 1·2가 `rookit-agent`를 사용한다. Docker는 에이전트를 http://localhost:8001/docs 에 replay 모드로 띄운다. Replay는 등록된 예시 답안만 채점하며, 자유 작문 채점은 [에이전트 설정](rookit-agent/README.md#run-with-the-web-app)의 live 모드가 필요하다. 영어 제출 기록은 이 브라우저에 저장된다.
