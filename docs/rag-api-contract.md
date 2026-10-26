# RAG 문제·평가 API

2026-10-23 구현 기준. 이전 `rootkit-api-proposal.md`의 점수 초안보다 이 계약을 우선한다. STEP 0는 기존 데모 API를 유지하고 STEP 1·2만 아래 흐름을 사용한다.

## 호출 경계

브라우저 → 인증된 Next.js `/api/rag/*` → FastAPI `/api/v1/*` → SQLite 순서다. Next.js가 `rootkit_session`의 사용자 ID를 읽고 내부 요청에 넣는다. 브라우저가 보낸 사용자 ID, 문제 내용, 기준, 승인·검토 상태는 사용하지 않는다.

FastAPI는 `Authorization: Bearer <AI_API_TOKEN>`을 요구한다. 토큰이 없거나 예제 값이면 사용 가능한 상태로 가장하지 않는다. 브라우저에는 이 토큰과 모델 키를 보내지 않는다. 사용자별 시도·기록 조회는 FastAPI에서도 소유권을 검사한다.

## 문제 표시와 기준 고정

`POST /api/v1/attempts`:

```json
{"user_id":"server-session-user-id","stage":1}
```

활성 문제집에서 검토를 통과한 해당 단계 문제를 무작위 선택하고, **응답하기 전에** 시도와 기준 스냅샷을 저장한다. 문제집이 없거나 해당 단계에 출제 가능한 문제가 없으면 명시적인 오류를 반환한다. 데모 문제로 대체하지 않는다.

응답은 `attempt_id`와 `exercise`다. `exercise`에는 다음 학습자용 필드만 포함한다.

| 필드 | 내용 |
| --- | --- |
| `id`, `version` | 문제 식별값과 버전 |
| `dataset_id`, `dataset_version` | 생성 근거 데이터셋 |
| `stage`, `language`, `recipient_group` | 단계, 언어, 명시된 수신자 그룹 |
| `title`, `scenario`, `requirements` | 제목, 상황, 요구사항 |
| `facts` | `{id, value, kind, origin, source_ids}` 배열. 답안에서 지켜야 할 사실을 표시 |
| `original`, `subject`, `recipient` | STEP 1 원문, 제목, 수신자. STEP 2 원문은 없음 |
| `source_ids` | 사용한 원문 식별값 |

기준 피드백, 승인 상태, 검토 사유와 내부 스냅샷은 학습자용 응답에 포함하지 않는다. 원문 ID는 데이터셋·버전과 함께 해석해야 한다.

`GET /api/v1/attempts/{attempt_id}?user_id=...`는 저장된 시도를 복원한다. 현재 활성 목록에 문제가 있는지 다시 검사하지 않으므로 데이터셋 교체 후에도 이전 문제를 재제출할 수 있다.

## 평가와 재시도

`POST /api/v1/evaluations`:

```json
{
  "user_id":"server-session-user-id",
  "attempt_id":"saved-attempt-id",
  "request_id":"unique-submission-request-id",
  "answer":{"subject":"Request for the report","body":"..."}
}
```

평가는 저장된 시도의 문제·문서·승인 용어·구성 패턴·기준만 사용한다. 제출 시 전체 문제집을 생성하지 않는다.

- 같은 시도·요청 ID·동일 답안: 저장된 결과를 반환한다.
- 같은 시도·요청 ID·다른 답안: `409` 충돌이다.
- 수정한 답안: 새로운 요청 ID로 같은 시도에 제출한다.
- 타임아웃 재시도: 답안이 같다면 같은 요청 ID를 유지한다.
- 완료 후 재평가: `match`, `needs_revision`, `insufficient_evidence` 응답을 받은 요청은 완료 상태다. 같은 답안을 다시 평가하려면 새 요청 ID를 사용한다. 웹은 완료 응답을 받으면 진행 중 요청을 해제하며 `다시 평가하기`에서 새 ID를 만든다.

성공 응답:

```json
{
  "attempt_id":"saved-attempt-id",
  "request_id":"unique-submission-request-id",
  "total":null,
  "status":"needs_revision",
  "summary":"요청 기한을 추가해 주세요.",
  "feedback":[{
    "criterion_id":"deadline",
    "category":"task",
    "explanation":"문제에서 정한 회신 기한이 빠졌습니다.",
    "suggestion":"문제에 제시된 기한을 포함한 영어 수정 예시",
    "evidence_ids":[]
  }]
}
```

이는 형식을 설명하는 예시이며 실제 모델 검토 결과가 아니다. `status`는 `match`, `needs_revision`, `insufficient_evidence` 중 하나이고 수치 점수는 없다. `company`, `task`, `general`은 회사 근거·문제 조건·일반 조언을 구분한다. 검토 실패 시 승인되지 않은 수정 예시를 정상 피드백으로 표시하지 않는다.

## 기록

`GET /api/v1/history?user_id=...`는 `{items:[{attempt_id,exercise,submissions}]}`를 반환한다. 각 제출은 `request_id`, `answer`, `result`, `created_at`을 포함한다. 브라우저 저장소를 지워도 서버 기록과 기존 시도는 남는다. STEP 0의 기존 데모 기록은 브라우저 저장 방식을 유지한다.

오류 응답은 `{error,code}` 형태다. 인증 실패, 소유권/없는 시도, 입력 오류, 요청 ID 충돌, 빈 문제집, 모델 설정 누락·응답 실패를 구분한다. Next.js는 upstream 응답 형태와 식별값을 확인하고 필요한 필드만 전달한다.
