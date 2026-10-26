"""작성: rootkit · 2026-10-23. Synthetic fixtures and model replies for tests only."""

from collections import defaultdict, deque
from copy import deepcopy
import json
from pathlib import Path

from app.models import Document


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def documents(label="a"):
    return [Document.model_validate(json.loads(line)) for line in (FIXTURES / f"dataset-{label}.jsonl").read_text().splitlines()]


def knowledge(label="a"):
    docs = documents(label)
    term = "출고 준비표" if label == "a" else "반입 확인서"
    return {
        "terms": [{
            "id": f"{label}-term", "term": term, "aliases": [f"{term} 약칭"],
            "evidence": [{"source_id": docs[0].id, "quote": term}],
            "applies_when": "delivery_status 상황에서 해당 업무 자료를 언급할 때",
        }],
        "patterns": [{
            "id": f"{label}-pattern", "recipient_group": "general", "language": "ko",
            "situation": "delivery_status", "sequence": ["purpose", "status", "request"],
            "applies_when": "일반 수신자에게 배송 확인을 요청할 때 관찰한 구성",
            "observations": [{
                "source_id": doc.id,
                "sections": [{"label": label_, "quote": paragraph} for label_, paragraph in zip(
                    ["purpose", "status", "request"], doc.body.split("\n\n")[1:4])],
            } for doc in docs[:3]],
        }],
    }


def exercise(label="a", stage=2):
    term = "출고 준비표" if label == "a" else "반입 확인서"
    deadline = "2026-11-12" if label == "a" else "2026-12-18"
    quantity = "12개" if label == "a" else "24개"
    scenario = f"연습용 상황: {term} {quantity} 검토를 {deadline} 15:00 KST까지 요청하세요. 배송 일정은 확인 중이며 확정되지 않았습니다."
    return {
        "id": f"{label}-exercise-{stage}", "stage": stage, "language": "ko",
        "recipient_group": "general", "situation": "delivery_status",
        "title": f"{term} 검토 요청", "scenario": scenario,
        "requirements": [f"{term} 검토 요청", f"{deadline} 15:00 KST 기한 전달", f"{quantity} 수량과 확인 중 상태 유지"],
        "facts": [
            {"id": "deadline", "value": deadline, "kind": "date", "origin": "exercise", "source_ids": []},
            {"id": "time", "value": "15:00", "kind": "time", "origin": "exercise", "source_ids": []},
            {"id": "timezone", "value": "KST", "kind": "timezone", "origin": "exercise", "source_ids": []},
            {"id": "quantity", "value": quantity, "kind": "quantity", "origin": "exercise", "source_ids": []},
            {"id": "status", "value": "확인 중", "kind": "status", "origin": "source", "source_ids": [f"{label}-mail-1"]},
        ],
        "original": f"{term} {quantity} 확인해 주세요. 배송 일정은 확인 중입니다." if stage == 1 else None,
        "subject": f"{term} 확인 요청", "recipient": "가상 운영팀 담당자",
        "source_ids": [f"{label}-mail-1", f"{label}-mail-2", f"{label}-mail-3"],
        "criteria": [{
            "criterion_id": "deadline", "defect": "요청 기한이 누락되거나 잘못되었습니다.",
            "correction": f"{deadline} 15:00 KST라는 요청 기한을 적어 주세요.",
            "reference_text": "요청 기한이 빠졌으므로 문제에서 지정한 기한을 추가해야 합니다.",
            "category": "task", "kind": "fact", "applies_when": "답안에 제시된 요청 기한이 없거나 잘못된 경우에만",
            "fact_ids": ["deadline", "time", "timezone"], "requirement_indexes": [1], "evidence_ids": [],
        }],
    }


def catalog(label="a"):
    return {"exercises": [exercise(label, 1), exercise(label, 2)]}


def catalog_review(label="a", passed=True):
    return {"reviews": [{"exercise_id": f"{label}-exercise-{stage}", "passed": passed,
                         "reasons": [] if passed else ["문제 조건에서 기준을 도출할 수 없습니다."]} for stage in (1, 2)]}


def feedback(applies=True, label="a", suggestion=None):
    deadline = "2026-11-12" if label == "a" else "2026-12-18"
    return {
        "summary": "요청 기한을 보완하세요." if applies else "문제의 조건을 충족했습니다.",
        "decisions": [{
            "criterion_id": "deadline", "applies": applies,
            "explanation": "요청 기한을 구체적으로 적어 주세요." if applies else "기한을 정확히 적었습니다.",
            "suggestion": suggestion or f"{deadline} 15:00 KST까지 검토해 주시면 감사하겠습니다.",
            "evidence_ids": [],
        }], "general_feedback": [],
    }


def semantics(applies=True, equivalent=True, passed=True):
    return {"passed": passed, "reasons": [] if passed else ["문제점과 수정 방향이 불명확합니다."],
            "decisions": [{"criterion_id": "deadline", "applies": applies, "semantic_equivalent": equivalent}]}


def facts(passed=True, feedback_ids=None):
    return {"passed": passed, "reasons": [] if passed else ["수정 예시의 날짜·수량·상태가 문제 조건과 다릅니다."],
            "checked_feedback_ids": ["deadline"] if feedback_ids is None else feedback_ids}


class ScriptedProvider:
    """Record every request and return explicit test-only structured responses."""

    def __init__(self):
        self.calls = []
        self.responses = defaultdict(deque)

    def add(self, task, *responses):
        self.responses[task].extend(deepcopy(responses))

    def complete(self, task, payload):
        self.calls.append((task, deepcopy(payload)))
        if not self.responses[task]:
            raise AssertionError(f"Unexpected model request: {task}")
        response = self.responses[task].popleft()
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)

    def count(self, task):
        return sum(name == task for name, _ in self.calls)
