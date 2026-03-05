"""
LangGraph 파이프라인 조립
4개 노드를 엣지로 연결하고 조건부 라우팅 설정

그래프 구조:
  START
    │
    ▼
  rubric_generator  ──(error)──► END
    │
    ▼
  rule_based_router ──(error)──► ensemble_evaluator (폴백)
    │
    ▼
  ensemble_evaluator ──(error)──► END
    │
    ▼
  hitl_node
    │
    ▼
  END
"""
from __future__ import annotations

import logging
from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from grading_pipeline.nodes.ensemble_evaluator import ensemble_evaluator_node
from grading_pipeline.nodes.hitl_node import hitl_node, init_neo4j
from grading_pipeline.nodes.rubric_generator import rubric_generator_node
from grading_pipeline.nodes.rule_based_router import rule_based_router_node
from grading_pipeline.state import GradingState, initial_state

logger = logging.getLogger(__name__)


# ── 조건부 엣지 함수 ──────────────────────────────────────────────────────────
def _after_rubric(state: GradingState) -> Literal["rule_based_router", "__end__"]:
    """루브릭 생성 실패 시 파이프라인 조기 종료"""
    if state.get("error_message") or not state.get("rubric"):
        logger.error("루브릭 생성 실패 — 파이프라인 종료: %s", state.get("error_message"))
        return END
    return "rule_based_router"


def _after_router(state: GradingState) -> Literal["ensemble_evaluator"]:
    """
    Rule-base 라우터 후 앙상블 평가로 진행
    (오류 발생 시에도 앙상블 평가는 수행 — rule_metadata 없이도 LLM 평가 가능)
    """
    if state.get("error_message"):
        logger.warning("Rule-base 오류 — 앙상블 평가로 폴백: %s", state.get("error_message"))
        # 오류 메시지 초기화 후 앙상블 진행 (비블로킹)
        state = {**state, "error_message": None}
    return "ensemble_evaluator"


def _after_ensemble(state: GradingState) -> Literal["hitl_node", "__end__"]:
    """앙상블 평가 실패 시 종료"""
    if state.get("error_message") or state.get("ensemble_score") is None:
        logger.error("앙상블 평가 실패 — 파이프라인 종료: %s", state.get("error_message"))
        return END
    return "hitl_node"


# ── 그래프 빌드 ───────────────────────────────────────────────────────────────
def build_graph(checkpointer=None) -> StateGraph:
    """
    LangGraph StateGraph 조립 및 반환

    Args:
        checkpointer: LangGraph 체크포인터 (기본: MemorySaver).
                      SQLiteSaver / RedisSaver 등 교체 가능.
    Returns:
        컴파일된 CompiledGraph
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder = StateGraph(GradingState)

    # ── 노드 등록 ─────────────────────────────────────────────────────────────
    builder.add_node("rubric_generator", rubric_generator_node)
    builder.add_node("rule_based_router", rule_based_router_node)
    builder.add_node("ensemble_evaluator", ensemble_evaluator_node)
    builder.add_node("hitl_node", hitl_node)

    # ── 엣지 연결 ─────────────────────────────────────────────────────────────
    builder.add_edge(START, "rubric_generator")

    builder.add_conditional_edges(
        "rubric_generator",
        _after_rubric,
        {"rule_based_router": "rule_based_router", END: END},
    )

    builder.add_conditional_edges(
        "rule_based_router",
        _after_router,
        {"ensemble_evaluator": "ensemble_evaluator"},
    )

    builder.add_conditional_edges(
        "ensemble_evaluator",
        _after_ensemble,
        {"hitl_node": "hitl_node", END: END},
    )

    builder.add_edge("hitl_node", END)

    return builder.compile(checkpointer=checkpointer)


# ── 편의 실행 함수 ────────────────────────────────────────────────────────────
def run_grading_pipeline(
    question: str,
    model_answer: str,
    student_answer: str,
    total_score: int,
    subject_tag: str = "auto",
    thread_id: str = "default",
    neo4j_uri: str | None = None,
    neo4j_user: str | None = None,
    neo4j_password: str | None = None,
) -> GradingState:
    """
    채점 파이프라인 실행 편의 함수

    Args:
        question:       평가 문항
        model_answer:   모범 답안
        student_answer: 학생 답안
        total_score:    문항 총점
        subject_tag:    과목 태그 ("auto" | "math" | "korean" | "science")
        thread_id:      LangGraph 체크포인트 스레드 ID
        neo4j_uri/user/password: Neo4j 접속 정보 (선택)

    Returns:
        최종 GradingState
    """
    # Neo4j 초기화 (제공된 경우)
    if neo4j_uri and neo4j_user and neo4j_password:
        init_neo4j(neo4j_uri, neo4j_user, neo4j_password)

    graph = build_graph()
    state = initial_state(
        question=question,
        model_answer=model_answer,
        student_answer=student_answer,
        total_score=total_score,
        subject_tag=subject_tag,
    )
    config = {"configurable": {"thread_id": thread_id}}

    result = graph.invoke(state, config=config)
    return result


# ── 개발용 빠른 실행 ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")

    result = run_grading_pipeline(
        question="이차방정식 x² - 5x + 6 = 0을 풀어라.",
        model_answer="x = 2 또는 x = 3",
        student_answer="x² - 5x + 6 = 0을 인수분해하면 (x-2)(x-3) = 0이므로 x = 2 또는 x = 3이다.",
        total_score=10,
        subject_tag="math",
    )

    print("\n" + "=" * 60)
    print("최종 채점 결과")
    print("=" * 60)
    print(f"최종 점수   : {result.get('final_score')} / {result.get('total_score')}")
    print(f"앙상블 점수 : {result.get('ensemble_score')}")
    print(f"교사 승인   : {result.get('teacher_approved')}")
    print(f"\n[최종 피드백]\n{result.get('final_feedback')}")
    if result.get("debate_log"):
        print(f"\n[토론 로그]\n" + "\n".join(result["debate_log"]))
    if result.get("error_message"):
        print(f"\n[오류]: {result.get('error_message')}")
