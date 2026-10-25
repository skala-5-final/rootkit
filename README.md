# rootkit

비즈니스 영어 이메일 온보딩 학습 서비스.

**새로운 세션은 [기획서.md](./기획서.md)부터 확인하세요.** 최신 결정 사항, 총 3단계 학습 흐름, 담당별 범위와 현재 구현 상태를 정리했습니다. 초기 API 예시는 `docs/rootkit-api-proposal.md`를 참고하되, 충돌 시 기획서의 최신 결정을 따릅니다.

## 구조

```
docs/                 설계 문서
prototype/            UI 프로토타입(정적 HTML, git 제외)
web/                  Next.js 앱 (App Router, TS, Tailwind, Drizzle ORM)
  src/db/schema.ts    DB 스키마 (users / exercises / submissions)
  drizzle/            생성된 SQL 마이그레이션
docker-compose.yml    db(Postgres 17) + migrate + web + agent
```

## Docker로 전부 띄우기

```bash
docker compose up -d --build
# http://localhost:3000, 헬스체크: http://localhost:3000/api/health
```

`migrate` 서비스가 마이그레이션과 데모 계정 시드를 마친 뒤 `web`이 시작됩니다.

- 데모 계정: 아이디 `rookie` / 비밀번호 `rootkit1234` (`SEED_LOGIN_ID`, `SEED_PASSWORD`로 변경 가능)
- DB 호스트 포트는 **5433**입니다. 로컬에 설치된 Postgres(5432)와 충돌하지 않게 하기 위함입니다.

## 인증

아이디/비밀번호 로그인 → JWT(HS256)를 httpOnly 쿠키 `rootkit_session`에 저장(7일).
`src/proxy.ts`가 `/kits`, `/learn/*`, `/history`, `/api/demo/*`를 보호합니다. 비밀번호는 scrypt로 해시합니다.
`JWT_SECRET`(32자 이상)이 필요합니다. 로컬은 `web/.env`, Docker는 루트 `.env` 또는 환경변수로 지정하세요.

## 로컬 개발 (DB만 Docker)

```bash
docker compose up -d db
cd web
cp .env.example .env   # 최초 1회
pnpm install
pnpm db:migrate
pnpm db:seed      # 데모 계정 생성
pnpm dev
```

## 스키마 변경

```bash
cd web
# src/db/schema.ts 수정 후
pnpm db:generate   # drizzle/ 에 SQL 생성 (커밋 대상)
pnpm db:migrate
pnpm db:studio     # DB 브라우저
```

## Writing-coach integration

Stages 1 and 2 load exercises and grading from `rookit-agent`; stage 0 uses local
blank-answer rules. Docker starts the agent on http://localhost:8000/docs in replay
mode. Replay accepts only exact fixture answers, not arbitrary writing. See
[agent setup](rookit-agent/README.md#run-with-the-web-app) for live-mode configuration.
