"""
LangGraph 공유 상태(State) 정의
전체 파이프라인에서 노드 간 공유되는 데이터 스키마
"""
from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict


# ── 루브릭 항목 스키마 ─────────────────────────────────────────────────────────
class RubricItem(TypedDict):
    criterion_id: str          # 예: "C1", "C2"
    description: str           # 평가 기준 설명
    max_score: int             # 해당 기준 배점
    bloom_level: str           # 해당 기준의 블룸 수준
    keywords: list[str]        # 채점 힌트 키워드


class Rubric(TypedDict):
    task_description: str      # 문항 요구사항 요약
    cognitive_level: str       # 최상위 블룸 수준
    total_score: int
    rubric_items: list[RubricItem]


# ── Rule-base 엔진 메타데이터 ──────────────────────────────────────────────────
class RuleMetadata(TypedDict):
    subject_tag: str                  # "math" | "korean" | "science"
    rule_score: float                 # 규칙 기반 1차 점수
    rule_max_score: float             # 규칙 기반 배점 합계
    errors: list[dict[str, Any]]      # 오류 상세 [{type, span, message}, ...]
    math_equivalence: Optional[dict]  # SymPy 검증 결과 (수학 문항만)
    keyword_hits: list[str]           # 감지된 핵심 키워드
    keyword_misses: list[str]         # 누락된 핵심 키워드


# ── 개별 평가 모델 결과 ────────────────────────────────────────────────────────
class EvaluatorResult(TypedDict):
    model_name: str                        # "gpt-5-mini" | "gemini-2.5-pro" | "llama-3-70b"
    criterion_scores: list[dict[str, Any]] # [{criterion_id, score, rationale}, ...]
    total_score: float
    feedback: str
    raw_response: str


# ── HITL 교사 피드백 ───────────────────────────────────────────────────────────
class TeacherCorrection(TypedDict):
    corrected_score: Optional[float]
    corrected_feedback: Optional[str]
    correction_note: str              # 교사 수정 사유


# ── 파이프라인 전체 공유 상태 ──────────────────────────────────────────────────
class GradingState(TypedDict):
    # ---- 입력 ----------------------------------------------------------------
    question: str                      # 평가 문항
    model_answer: str                  # 모범 답안
    student_answer: str                # 학생 답안
    total_score: int                   # 문항 총점
    subject_tag: str                   # "math" | "korean" | "science" | "auto"

    # ---- Node 1: Rubric Generator 출력 ---------------------------------------
    rubric: Optional[Rubric]

    # ---- Node 2: Rule-based Router 출력 --------------------------------------
    rule_metadata: Optional[RuleMetadata]

    # ---- Node 3: Ensemble Evaluator 출력 -------------------------------------
    evaluator_results: list[EvaluatorResult]  # 각 모델 독립 평가 결과
    debate_log: list[str]                     # 편차 발생 시 토론 로그
    ensemble_score: Optional[float]           # 최종 앙상블 가중 평균 점수
    ensemble_feedback: Optional[str]          # 종합 피드백 문단

    # ---- Node 4: HITL 출력 ---------------------------------------------------
    teacher_approved: Optional[bool]
    teacher_correction: Optional[TeacherCorrection]
    final_score: Optional[float]
    final_feedback: Optional[str]

    # ---- 파이프라인 제어 ------------------------------------------------------
    error_message: Optional[str]       # 노드 오류 메시지
    route: Optional[str]               # 라우팅 결정값 ("math" | "korean" | "science" | "general")


def initial_state(
    question: str,
    model_answer: str,
    student_answer: str,
    total_score: int,
    subject_tag: str = "auto",
) -> GradingState:
    """파이프라인 초기 상태 생성 팩토리 함수"""
    return GradingState(
        question=question,
        model_answer=model_answer,
        student_answer=student_answer,
        total_score=total_score,
        subject_tag=subject_tag,
        rubric=None,
        rule_metadata=None,
        evaluator_results=[],
        debate_log=[],
        ensemble_score=None,
        ensemble_feedback=None,
        teacher_approved=None,
        teacher_correction=None,
        final_score=None,
        final_feedback=None,
        error_message=None,
        route=None,
    )
