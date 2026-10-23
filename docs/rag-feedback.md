# 회사 데이터로 문제·평가 기준 운영하기

2026-10-23 구현. 이 저장소에는 이전 FastAPI/RAG 구현이 없었으므로 `ai/app/`과 `web/src/lib/rag-*`를 추가했다. STEP 0와 기존 인증은 유지한다. STEP 1·2는 아래 절차로 활성화한 문제를 사용하며 고정 데모로 대체하지 않는다.

## 재사용 원칙과 변경되는 데이터

| 구분 | 위치·역할 | 데이터 교체 시 |
| --- | --- | --- |
| 공통 원칙 | `ai/app/prompts.py`의 `PRINCIPLES`, 버전 | 공식 용어, 조건부 피드백, 사실 보존, 의미 동등성을 재사용 |
| 회사 지식 | 데이터 버전별 문서·용어·구성 패턴 | 새 원문 근거로 다시 추출. 공식 용어와 별칭은 사람이 승인 |
| 문제별 기준 | 문제집의 `criteria`, 검토 결과 | 문제와 함께 생성하고 별도 AI 요청으로 검토 |
| 진행 중인 시도 | 문제 표시 전에 저장하는 전체 스냅샷 | 기존 문서·용어·기준을 유지 |

파인튜닝을 실행하지 않는다. 회사 지식 추출, 문제·기준 생성, 생성 결과 검토는 서로 다른 작업이며, 답안 제출 시에는 저장된 시도만 평가한다.

## 환경 설정

저장소 루트에서 처음 한 번:

```bash
cp web/.env.example web/.env  # 기존 파일이 있으면 생략
cp ai/.env.example ai/.env    # 기존 파일이 있으면 생략
```

`web/.env`의 `JWT_SECRET`과 `AI_API_TOKEN`에는 각각 다른 임의의 키를 설정한다. `openssl rand -base64 48`로 생성할 수 있다. `ai/.env`에는 다음 값을 설정한다.

| 변수 | 의미 |
| --- | --- |
| `MODEL_API_BASE_URL` | JSON 모드와 `/chat/completions`를 지원하는 제공자의 API 기준 주소. 기본 `https://api.openai.com/v1` |
| `MODEL_API_KEY` | 해당 제공자의 실제 API 키 |
| `MODEL_NAME` | 해당 계정에서 사용 가능한 모델 ID. 자동으로 모델을 선택하지 않음 |
| `AI_DB_PATH` | 로컬 SQLite 경로. 기본 `data/rootkit.sqlite3` |

키나 모델 이름이 비어 있으면 생성·평가가 명시적으로 실패한다. 가짜 문제집, 검토 성공 또는 피드백을 만들지 않는다. 내부 API 인증키와 외부 모델 키는 별개다.

### 반복 보류와 모델 설정

`ai/.env`에서 생성·평가·검토 모델을 구분할 수 있다. 역할별 이름이 비어 있으면 `MODEL_NAME`을 사용한다. 로컬 실행에는 다음 설정을 적용했다. 계정에서 사용할 수 있는 모델만 지정해야 한다.

```dotenv
MODEL_NAME=gpt-4.1-mini
MODEL_GENERATION_NAME=gpt-4.1-mini
MODEL_EVALUATION_NAME=gpt-5.4-mini
MODEL_EVALUATION_REASONING_EFFORT=medium
MODEL_REVIEW_NAME=gpt-5.4-mini
MODEL_REVIEW_REASONING_EFFORT=high
MODEL_FALLBACK_NAME=
MODEL_RESPONSE_FORMAT=json_schema
MODEL_TEMPERATURE=
MODEL_TIMEOUT_SECONDS=45
MODEL_CATALOG_TIMEOUT_SECONDS=90
MODEL_MAX_RETRIES=1
EVALUATION_TIMEOUT_SECONDS=180
EVALUATION_REPAIR_ATTEMPTS=1
```

- `json_schema`는 지정한 JSON 구조를 요구한다. 이를 지원하지 않는 제공자는 `json_object`를 명시한다. 응답 형식 준수만으로 평가 내용이 정확해지는 것은 아니므로 별도 검토는 유지한다.
- 현재는 평가 모델의 추론을 `medium`, 검토 모델을 `high`로 설정하고, 호환성을 위해 `MODEL_TEMPERATURE`를 비워 요청에서 제외한다. 각 추론 설정은 해당 역할의 기본 모델에만 전달하며 문제 생성·지식 추출 및 통신 장애용 대체 모델에는 전달하지 않는다. 추론을 지원하지 않는 모델은 해당 역할의 `*_REASONING_EFFORT`를 비운다. 지원 범위는 [모델 문서](https://developers.openai.com/api/docs/models/gpt-5.4-mini)를 따른다.
- 통신 오류·429·서버 오류에만 같은 모델을 최대 한 번 재시도하고, 계속 실패하면 대체 모델이 지정된 경우에만 한 번 사용한다. 현재 로컬 설정은 대체 모델을 비워 두었다. 인증·권한·잘못된 요청 오류나 검토 불합격을 대체 모델로 우회하지 않는다.
- 피드백의 형식·적용 조건·의미·수정 사실 검토가 실패하면 사유를 반영해 생성부터 최대 한 번 개선하고 다시 독립 검토한다. 두 번째도 실패하면 보류한다. `EVALUATION_REPAIR_ATTEMPTS=0`이면 자동 개선을 끈다.
- 의미 검토는 답안의 해당 구절과 조건 판단 사유를 먼저 작성한 뒤 피드백을 검토한다. 비어 있지 않은 인용이 실제 답안에 없으면 코드 검사에서도 반려한다. 한국어 문제의 수정 제안은 메일에 바로 사용할 수 있는 한국어 문장으로 작성한다.
- 전체 평가의 모델 호출·재시도·개선은 기본 120초, 현재 로컬 설정 및 최대값 180초의 공통 예산 안에서 수행한다. 서버 프록시는 200초, 브라우저는 210초를 기다려 모델 처리보다 먼저 연결이 끊기는 것을 줄인다. SQLite 잠금 대기는 별도로 발생할 수 있다.

설정 변경 후 `docker compose up -d --force-recreate ai`를 실행한다. API 키는 기존 `MODEL_API_KEY`에 보관하며 로그나 이 문서에 기록하지 않는다. 검토 기록에는 호출 모델·소요 시간·실패 코드와 개선 전후 결과를 남긴다.

### 로컬 FastAPI

```bash
cd ai
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
set -a
. ../web/.env
. ./.env
set +a
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

CLI를 실행하는 다른 터미널에서도 `ai/`로 이동해 같은 환경변수를 읽는다. 아래 모든 로컬 명령은 `ai/` 기준이다. `--db /절대/경로.sqlite3`를 `app.cli` 바로 다음에 지정할 수도 있다. 웹과 CLI가 같은 SQLite 파일을 사용해야 한다.

### Docker

루트에서 `docker compose up -d --build`로 웹·PostgreSQL·FastAPI를 실행한다. FastAPI는 `web/.env`의 내부 인증키와 `ai/.env`의 모델 설정을 읽고 SQLite를 `ai-data` 볼륨의 `/data/rootkit.sqlite3`에 저장한다. `ai/.env`는 선택 파일이므로 없어도 기존 STEP 0 실행을 막지 않지만 모델 요청은 설정 오류가 난다.

컨테이너에서 같은 CLI를 실행하려면 입력 파일을 복사하고 명령 앞부분을 바꾼다.

```bash
docker compose cp ai/fixtures/dataset-a.jsonl ai:/tmp/dataset-a.jsonl
docker compose exec ai python -m app.cli import --dataset A --file /tmp/dataset-a.jsonl
docker compose exec ai python -m app.cli status
```

이후 아래 `.venv/bin/python -m app.cli`를 `docker compose exec ai python -m app.cli`로 바꿔 실행한다. 모델 설정을 바꾸면 AI 컨테이너를 다시 생성해야 한다. 데이터 볼륨을 삭제하면 이전 시도와 원문도 없어지므로 일반적인 교체에는 볼륨 삭제가 필요하지 않다.

## 입력 JSONL

지원 형식은 UTF-8 `.jsonl`이며 한 줄에 문서 객체 하나다. PDF·DOCX·CSV 파서는 이번 범위에 없다. 빈 데이터셋, 중복 ID, 잘못된 유형·필드·인코딩은 반입 오류다. 첫 BOM, 빈 줄, CRLF/LF는 처리하며 본문의 문단 순서를 보존한다.

```json
{"id":"mail-01","kind":"email","title":"일정 확인","body":"Hi team,\n\nPlease confirm the delivery schedule.\n\nThank you.","recipient_group":"general","language":"en","case_id":"delivery-case-01","situation":"delivery_confirmation"}
```

| 필드 | 규칙 |
| --- | --- |
| `id` | 데이터 버전 안에서 유일한 원문 ID |
| `kind` | `email` 또는 `report`. 보고서는 메일 구성 근거가 아님 |
| `title`, `body` | 비어 있지 않은 제목과 **전체 본문**. 본문은 최대 100,000자 |
| `recipient_group` | 명시적으로 `customer` 또는 `general`. 상사·동료·협력사는 기본 `general` |
| `language` | 일관된 언어 표기, 예: `en`, `ko`. 그룹 비교는 입력값 기준 |
| `case_id` | 독립적인 업무 사례 ID. 같은 사례의 복제 메일은 같은 ID 사용 |
| `situation` | 적용할 업무 상황의 일관된 분류명 |

모든 필드를 명시한다. 고객이라는 단어로 수신자 그룹을 추측하지 않는다. `fixtures/dataset-a.jsonl`, `dataset-b.jsonl`은 가상의 테스트 자료이며 실제 회사 규정이나 실제 모델 생성 결과가 아니다.

## 최초 등록 → 용어 승인 → 문제집 활성화

```bash
.venv/bin/python -m app.cli import --dataset A --file fixtures/dataset-a.jsonl
.venv/bin/python -m app.cli terms extract --dataset A --version 1
.venv/bin/python -m app.cli terms list --dataset A --version 1
```

`import` 출력의 `version`을 이후 명령에 사용한다. `terms extract`는 용어 후보와 상황별 구성 패턴을 한 번에 추출한다. 후보의 원문 인용·적용 조건을 확인한 뒤 필요한 용어만 승인한다.

```bash
.venv/bin/python -m app.cli terms approve --dataset A --version 1 --term-id '<후보 ID>' --alias '<허용 별칭>'
.venv/bin/python -m app.cli catalog generate --dataset A --version 1
.venv/bin/python -m app.cli catalog review --catalog '<생성 결과 catalog_id>'
.venv/bin/python -m app.cli catalog show --catalog '<생성 결과 catalog_id>'
.venv/bin/python -m app.cli catalog activate --catalog '<생성 결과 catalog_id>'
.venv/bin/python -m app.cli status
```

`--alias`는 여러 번 줄 수 있다. AI가 제안한 별칭을 자동 승인하지 않는다. 용어 추출을 다시 하면 해당 버전의 승인 상태는 초기화되며, 이미 생성된 문제집·시도의 스냅샷은 유지한다. 승인 변경을 새 출제에 반영하려면 새 문제집을 생성·검토·활성화한다.

문제집은 생성만으로 활성화되지 않는다. 모든 생성 문제를 별도의 모델 요청으로 검토하고, 원문 ID·사실·회사 규칙·조건부 기준에 대한 코드 검사도 통과한 문제만 출제한다. 일부 실패한 문제는 사유와 함께 제외한다. 통과 문제가 0개이면 활성화할 수 없다. 특정 단계 문제가 없으면 웹에서 그 상태를 명시한다.

### 연습용 더미 문제집

`fixtures/practice-demo.jsonl`은 가상 이메일 4건이고, `fixtures/practice-demo-catalog.json`은 이 자료를 바탕으로 직접 작성한 STEP 1·2 연습 문제다. 실제 회사 자료나 모델이 생성한 문제로 표시하지 않는다. 문제집을 가져오는 작업은 후보 등록이며, 기존 독립 AI 검토를 통과해야 활성화할 수 있다.

```bash
.venv/bin/python -m app.cli import --dataset practice-demo --file fixtures/practice-demo.jsonl
.venv/bin/python -m app.cli catalog import --dataset practice-demo --version 1 --file fixtures/practice-demo-catalog.json
.venv/bin/python -m app.cli catalog review --catalog '<가져온 문제집 catalog_id>'
.venv/bin/python -m app.cli catalog activate --catalog '<검토를 통과한 catalog_id>'
```

데이터셋을 다시 가져왔으면 출력된 새 `version`을 사용한다. 수동 문제집도 같은 사실·출처 검사를 받으며, 회사 기준이 필요하면 먼저 해당 버전의 지식 추출과 용어 승인을 진행한다. 가상 연습 문제는 공개된 사실과 과제 요건만 평가하므로 회사 용어 승인이 필요하지 않다. 자동 생성 시 모델에 기본 두 문항을 요청한다. 문제집 생성·검토의 개별 호출은 기본 90초, 답안 평가·검토의 개별 호출은 기본 25초(현재 로컬 45초)이며, 답안 전체 처리에는 위 공통 시간 예산을 적용한다.

2026-10-23 로컬 Docker 실행에서는 `practice-demo:1`의 수동 작성 문제 4개(STEP 1·2 각각 2개)를 출처 검사와 실제 `gpt-4.1-mini` 검토 후 활성화했다. 활성 문제집 ID는 `bcbde96a-6220-4d48-9731-918fffc656ba`다. 앞선 `gpt-4o-mini` 검토는 초안을 답안으로 판단하여 실패했으며, 실패 기록도 SQLite에 유지했다. 최초 등록 당시에는 문제집 검토만 `gpt-4.1-mini`로 실행했다. 이후 반복 보류 문제를 수정하면서 답안 평가와 독립 검토에 위 역할별 설정을 적용했다. 실제 재평가 결과는 [검증 기록](./rag-verification.md)에 구분해 기록한다.

## 문서 추가와 활성 데이터 교체

기존 A 문서에 추가하려면:

```bash
.venv/bin/python -m app.cli append --dataset A --file additional.jsonl
```

새 버전은 최신 A 문서와 추가 문서를 포함한다. 기존 ID 중복은 오류다. 원문·용어·문제집을 직접 덮어쓰지 않는다. 출력된 새 버전으로 추출·승인·생성·검토·활성화를 다시 수행한다. 이전 버전의 승인 용어는 자동 상속하지 않는다.

문서를 통째로 바꾸되 용어를 먼저 승인하고 싶으면 `import --dataset B --file ...` 이후 위의 분리된 절차를 사용한다. 같은 데이터셋 ID로 `import`해도 새 버전을 만들며 이전 원문은 섞지 않는다.

용어 승인 없이 전체 자동 파이프라인을 한 번 실행하려면:

```bash
.venv/bin/python -m app.cli replace --dataset B --file fixtures/dataset-b.jsonl
```

`replace`는 반입 → 지식 추출 → 문제·기준 생성 → 별도 검토 → 활성화를 실행한다. 후보 용어를 공식 용어로 자동 승인하지 않는다. 이 명령은 모델 호출을 포함한다. 마지막 활성 포인터 변경만 트랜잭션으로 수행하므로 중간 실패나 검토 탈락 시 기존 활성 문제집은 유지된다. 새 버전과 실패 사유는 조사할 수 있게 남는다.

## 평가 원칙과 검토

- 공식 용어와 사람이 승인한 별칭만 강제 기준으로 사용한다. 일반적인 정중한 표현은 의미가 같으면 허용한다.
- 구성 패턴은 같은 수신자 그룹·언어·업무 상황의 전체 메일에서 찾는다. 독립 사례 ID, 다른 본문, 원문 인용의 순서를 검사한다. 최소 3건은 필요한 근거량이지 정확도 보장이 아니다. 근거 부족·상충 시 패턴을 보류한다.
- 원문 사실은 `origin: source`와 근거 ID를 저장한다. 연습용 새 사실은 `origin: exercise`로 표시하고 학습 화면의 조건으로 공개한다.
- 기준은 `criterion_id`, `defect`, `correction`, `reference_text`와 `applies_when`, 관련 사실·요구사항·근거를 함께 저장한다. 충족된 조건에는 결함 피드백을 출력하지 않는다.
- 답안 평가 후 별도 모델 요청으로 적용 조건과 의미 동등성을 검토하고, 또 다른 요청으로 수정 예시의 날짜·수량·상태 등 사실을 검토한다. 표현이 다르다는 이유만으로 불일치로 처리하지 않는다.
- 개선 후에도 검토가 일치하지 않으면 `insufficient_evidence`로 보관하고 승인되지 않은 수정 예시를 숨긴다. 화면에는 `판단 보류 · 검토 확인 필요`로 표시하며, 이 상태만으로 자료 부족이나 오답이라고 판단하지 않는다. 모델 호출·설정 실패는 성공 결과로 저장하지 않는다.
- 회사 근거 `company`, 문제 조건 `task`, 명시된 일반 조언 `general`을 구분한다. STEP 1·2는 항상 `total: null`이다.

## 문제 표시부터 재제출까지

로그인 → 학습 키트 → STEP 1 또는 2 → 문제 시작 시 서버가 활성 문제집에서 무작위로 선택하고 시도를 저장한다. 문제 화면에는 데이터셋·버전·요구사항·사실이 표시되며 내부 기준은 내려보내지 않는다.

이때 `corpus_version`, `term_version`, `criteria_version`과 문제·근거·지식 스냅샷이 고정된다. A 문제를 띄운 뒤 B를 활성화해도 첫 제출과 재제출은 A 기준을 사용한다. 이후 시작하는 새 문제는 B에서 가져온다. 기록 화면에서 이전 시도를 다시 열어 제출할 수 있다.

동일 요청 ID와 동일 답안은 저장된 결과를 재사용한다. 다른 답안을 같은 요청 ID로 보내면 `409`다. 웹은 타임아웃이나 통신 실패로 결과를 받지 못했을 때 동일 요청을 유지해 `이전 평가 결과 확인하기`로 이어간다. 완료된 결과를 받으면 진행 중 요청을 지우며, 이후 `다시 평가하기`는 답안을 수정하지 않아도 새 ID로 평가한다. 새로고침 후에도 답안은 유지한다. 이전 버전에서 남은 완료 요청은 저장 결과를 한 번 확인한 뒤 새 평가로 전환한다. 상세 계약은 [API 문서](./rag-api-contract.md)에 있다.

## 사람이 보는 검토 기록

```bash
.venv/bin/python -m app.cli reviews export --output data/review-export.json
```

내보내기에는 원문·지식·문제·기준·검토 사유와 작업 이력이 포함된다. 통과 결과를 표본 검토하고 실패·불일치의 원문 근거를 확인한다. 내보낸 내부 자료를 학습자용 API로 전달하지 않는다. 사람이 모든 문제를 승인해야 출제되는 구조는 아니다.

## 범위와 제약

단일 회사 MVP다. 문서를 한 번에 모델 컨텍스트로 전달하므로 모델의 컨텍스트 한도를 넘는 대규모 자료는 나눠 정리해야 한다. 벡터 DB·작업 큐·대규모 관리자 화면·PDF 추출은 추가하지 않았다. 원문과 승인 근거를 보존한 SQLite 스냅샷을 평가 컨텍스트로 사용한다.

평가는 SQLite 쓰기 트랜잭션에서 직렬 처리해 동시 중복 요청을 막는다. 동시 사용량이 많으면 대기·타임아웃이 생길 수 있으므로 같은 요청 ID로 재시도한다. 오래된 버전·시도는 자동 삭제하지 않는다. 모델이 잘못 판단할 가능성은 남으며, 모의 모델 테스트가 언어 평가의 정확성을 보장하지 않는다.
