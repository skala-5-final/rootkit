"""작성: rootkit · 2026-10-23. Immutable, validated RAG interchange models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class Document(Model):
    id: str = Field(min_length=1, max_length=200)
    kind: Literal["email", "report"]
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=100000)
    recipient_group: Literal["customer", "general"]
    language: str = Field(min_length=2, max_length=30)
    case_id: str = Field(min_length=1, max_length=200)
    situation: str = Field(min_length=1, max_length=200)

    @field_validator("body", mode="before")
    @classmethod
    def normalize_newlines(cls, value):
        return value.replace("\r\n", "\n").replace("\r", "\n") if isinstance(value, str) else value


class Evidence(Model):
    source_id: str
    quote: str = Field(min_length=1)


class TermCandidate(Model):
    id: str = Field(min_length=1)
    term: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(min_length=1)
    applies_when: str = Field(min_length=1)


class PatternSection(Model):
    label: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class PatternObservation(Model):
    source_id: str
    sections: list[PatternSection] = Field(min_length=2)


class CompositionPattern(Model):
    id: str = Field(min_length=1)
    recipient_group: Literal["customer", "general"]
    language: str
    situation: str = Field(min_length=1)
    sequence: list[str] = Field(min_length=2)
    observations: list[PatternObservation] = Field(min_length=1)
    applies_when: str = Field(min_length=1)


class KnowledgeProposal(Model):
    terms: list[TermCandidate]
    patterns: list[CompositionPattern]


class Fact(Model):
    id: str = Field(min_length=1)
    value: str = Field(min_length=1)
    kind: Literal["date", "time", "timezone", "quantity", "amount", "target", "intent", "status", "other"]
    origin: Literal["source", "exercise"]
    source_ids: list[str] = Field(default_factory=list)


class ReferenceFeedback(Model):
    criterion_id: str = Field(min_length=1)
    defect: str = Field(min_length=1)
    correction: str = Field(min_length=1)
    reference_text: str = Field(min_length=1)
    category: Literal["company", "task", "general"]
    kind: Literal["fact", "requirement", "term", "pattern", "general"]
    applies_when: str = Field(min_length=1)
    fact_ids: list[str] = Field(default_factory=list)
    requirement_indexes: list[int] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    term_id: str | None = None
    pattern_id: str | None = None


class ExerciseDraft(Model):
    id: str = Field(min_length=1, max_length=200)
    stage: Literal[1, 2]
    language: str
    recipient_group: Literal["customer", "general"]
    situation: str = Field(min_length=1)
    title: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    requirements: list[str] = Field(min_length=1)
    facts: list[Fact]
    original: str | None = None
    subject: str = ""
    recipient: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    criteria: list[ReferenceFeedback] = Field(min_length=1)

    @model_validator(mode="after")
    def needs_rewrite_original(self):
        if self.stage == 1 and not self.original:
            raise ValueError("STEP 1 requires the original email")
        if self.stage == 2 and self.original is not None:
            raise ValueError("STEP 2 must not include a rewrite original")
        if len({fact.id for fact in self.facts}) != len(self.facts):
            raise ValueError("fact IDs must be unique")
        if len({criterion.criterion_id for criterion in self.criteria}) != len(self.criteria):
            raise ValueError("criterion IDs must be unique")
        if any(criterion.criterion_id.startswith("general-advice-") for criterion in self.criteria):
            raise ValueError("general-advice- is reserved for optional general feedback IDs")
        return self


class CatalogProposal(Model):
    exercises: list[ExerciseDraft] = Field(min_length=1, max_length=100)


class ExerciseReview(Model):
    exercise_id: str
    passed: bool
    reasons: list[str]


class CatalogReview(Model):
    reviews: list[ExerciseReview]


class Answer(Model):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)


class CriterionDecision(Model):
    criterion_id: str
    applies: bool
    explanation: str
    suggestion: str = Field(description="applies=true이면 학습자가 메일에 바로 사용할 수 있는 구체적인 교체 문장/수정 예시. '정중하게 작성하세요' 같은 작성 지시만 쓰지 말고 문제의 사실과 언어를 보존한다.")
    evidence_ids: list[str]


class GeneralFeedback(Model):
    explanation: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)


class EvaluationProposal(Model):
    summary: str = Field(min_length=1)
    decisions: list[CriterionDecision]
    general_feedback: list[GeneralFeedback] = Field(default_factory=list, max_length=3)


class SemanticDecision(Model):
    criterion_id: str
    answer_evidence: str = Field(default="", description="proposed_decision을 판단하기 전에 직접 확인한 learner_answer의 subject 또는 body에서 연속된 구절을 그대로 인용한다. 인용부호를 덧붙이지 않는다. 필요한 표현이 실제로 없어 인용할 수 없는 경우 빈 문자열. 문제 조건·기준·AI 피드백을 답안처럼 인용하지 않는다.")
    reason: str = Field(default="", min_length=1, description="인용한 실제 답안이 해당 적용 조건을 충족하는지 구체적인 한국어 사유. '정중하게 요청한다' 같은 작성 요령과 수신자에게 실제로 요청하는 문장을 구별하고, proposed_decision의 주장에 의존하지 않고 먼저 판단한다.")
    applies: bool
    semantic_equivalent: bool = Field(description="AI 피드백이 실제 답안의 결함과 올바른 수정 방향을 정확하게 설명하면 true. 답안 자체가 틀려도 정확한 지적은 true이며 기준 문장과 표현이 같을 필요는 없다. applies=false인 조건에 부당한 결함 지적을 하지 않은 경우도 true.")


class SemanticReview(Model):
    decisions: list[SemanticDecision]
    passed: bool = Field(description="학습자 답안의 정답 여부가 아닌 AI 피드백의 정확성 판정. 모든 개별 applies 판단이 제안과 일치하고 semantic_equivalent=true이며 일반 조언 등 추가 피드백에도 구체적인 오류가 없으면 반드시 true. 답안이 틀렸어도 정확히 지적·수정한 피드백은 true. 피드백 자체의 구체적인 오류가 있을 때만 false.")
    reasons: list[str] = Field(description="passed=true이면 빈 배열. false이면 해당 criterion/feedback ID와 AI 피드백 자체의 구체적인 잘못을 적는다. 원래 답안의 결함이나 '피드백이 정확히 지적했다'는 설명은 반려 사유가 아니다.")


class FactsReview(Model):
    passed: bool = Field(description="모든 수정 제안의 사실이 문제에 공개된 조건과 일치하면 true. 학습자의 원래 답안에 있던 결함은 false의 사유가 아니며, 틀린 날짜·수량·상태를 문제의 올바른 값으로 고친 제안은 통과한다.")
    reasons: list[str]
    checked_feedback_ids: list[str]


class Feedback(Model):
    criterion_id: str
    category: Literal["company", "task", "general"]
    explanation: str
    suggestion: str
    evidence_ids: list[str]


class EvaluationResult(Model):
    attempt_id: str
    request_id: str
    total: None = None
    status: Literal["match", "needs_revision", "insufficient_evidence"]
    summary: str
    feedback: list[Feedback]


class AttemptRequest(Model):
    user_id: str = Field(min_length=1, max_length=200)
    stage: Literal[1, 2]


class EvaluationRequest(Model):
    user_id: str = Field(min_length=1, max_length=200)
    attempt_id: str = Field(min_length=1, max_length=200)
    request_id: str = Field(min_length=1, max_length=200)
    answer: Answer


class ExerciseDisplay(Model):
    id: str
    version: int = Field(ge=1)
    dataset_id: str
    dataset_version: int = Field(ge=1)
    stage: Literal[1, 2]
    language: str
    recipient_group: Literal["customer", "general"]
    title: str
    scenario: str
    requirements: list[str]
    facts: list[Fact]
    original: str | None
    subject: str
    recipient: str
    source_ids: list[str]


class AttemptResponse(Model):
    attempt_id: str
    exercise: ExerciseDisplay


class HistorySubmission(Model):
    request_id: str
    answer: Answer
    result: EvaluationResult
    created_at: str


class HistoryItem(AttemptResponse):
    submissions: list[HistorySubmission]


class HistoryResponse(Model):
    items: list[HistoryItem]
