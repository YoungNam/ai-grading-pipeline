"""
Node 4: Human-in-the-Loop (HITL)
교사 검수 체크포인트 — LangGraph interrupt() 기반 실행 중단 후 재개

흐름:
  1. CheckpointNode: 현재 채점 결과를 Neo4j에 임시 저장
  2. interrupt(): 교사 UI로 제어권 반환
  3. 교사 승인/수정 후 resume() 호출로 재개
  4. 최종 결과를 Neo4j 그래프에 영구 저장
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from grading_pipeline.state import GradingState, TeacherCorrection

logger = logging.getLogger(__name__)


# ── Neo4j 클라이언트 (선택적 의존성) ─────────────────────────────────────────
try:
    from neo4j import GraphDatabase

    _neo4j_driver = None  # graph.py 또는 설정 모듈에서 초기화

    def init_neo4j(uri: str, user: str, password: str) -> None:
        global _neo4j_driver
        _neo4j_driver = GraphDatabase.driver(uri, auth=(user, password))
        logger.info("Neo4j 연결 완료: %s", uri)

    _HAS_NEO4J = True
except ImportError:
    _HAS_NEO4J = False
    logger.warning("neo4j 드라이버 미설치 — Neo4j 저장 기능 비활성화")
    def init_neo4j(uri: str, user: str, password: str) -> None:  # type: ignore[misc]
        pass


# ── HITL 노드 ─────────────────────────────────────────────────────────────────
def hitl_node(state: GradingState) -> GradingState:
    """
    LangGraph Node 4: HITL

    입력 상태 필드: ensemble_score, ensemble_feedback, rubric, evaluator_results
    출력 상태 필드: teacher_approved, teacher_correction, final_score, final_feedback

    NOTE: 실제 LangGraph 환경에서는 interrupt()를 사용하여 교사 UI로 제어권을 반환합니다.
          아래 구현은 interrupt() 호출 지점과 resume 후 처리 로직을 구분하여 작성되었습니다.
    """
    logger.info("[Node4] HITL 체크포인트 시작")

    # ── 1단계: 임시 저장 (체크포인트) ─────────────────────────────────────────
    _save_checkpoint(state)

    # ── 2단계: 교사 UI로 제어권 반환 ──────────────────────────────────────────
    #
    # LangGraph interrupt() 패턴:
    #   from langgraph.types import interrupt
    #   teacher_input = interrupt({
    #       "message": "교사 검수를 요청합니다.",
    #       "ensemble_score": state["ensemble_score"],
    #       "ensemble_feedback": state["ensemble_feedback"],
    #       "rubric": state["rubric"],
    #       "evaluator_results": state["evaluator_results"],
    #   })
    #
    # 아래는 resume() 후 수신된 teacher_input을 처리하는 로직입니다.
    # 실제 배포 시 위 주석 해제 후 아래 _mock_teacher_input() 제거하세요.
    teacher_input = _mock_teacher_input(state)

    # ── 3단계: 교사 입력 처리 ─────────────────────────────────────────────────
    approved: bool = teacher_input.get("approved", False)
    correction: Optional[TeacherCorrection] = None

    if approved:
        final_score = state["ensemble_score"]
        final_feedback = state["ensemble_feedback"]
        logger.info("[Node4] 교사 승인 완료 — 최종 점수: %.1f", final_score)
    else:
        corrected_score = teacher_input.get("corrected_score")
        corrected_feedback = teacher_input.get("corrected_feedback")
        correction_note = teacher_input.get("correction_note", "교사 수정")

        correction = TeacherCorrection(
            corrected_score=corrected_score,
            corrected_feedback=corrected_feedback,
            correction_note=correction_note,
        )
        final_score = corrected_score if corrected_score is not None else state["ensemble_score"]
        final_feedback = corrected_feedback if corrected_feedback else state["ensemble_feedback"]
        logger.info("[Node4] 교사 수정 적용 — 최종 점수: %.1f", final_score)

    # ── 4단계: Neo4j 영구 저장 ────────────────────────────────────────────────
    updated_state = {
        **state,
        "teacher_approved": approved,
        "teacher_correction": correction,
        "final_score": final_score,
        "final_feedback": final_feedback,
    }
    _save_final_result(updated_state)

    return updated_state


# ── Neo4j 저장 함수 ───────────────────────────────────────────────────────────
def _save_checkpoint(state: GradingState) -> None:
    """앙상블 결과를 Neo4j에 임시 노드로 저장"""
    if not _HAS_NEO4J or _neo4j_driver is None:
        logger.debug("[Node4] Neo4j 비활성화 — 체크포인트 스킵")
        return

    cypher = """
    MERGE (s:StudentAnswer {id: $answer_id})
    SET s.student_answer = $student_answer,
        s.question = $question,
        s.updated_at = $timestamp
    MERGE (e:EnsembleResult {answer_id: $answer_id})
    SET e.ensemble_score = $ensemble_score,
        e.ensemble_feedback = $ensemble_feedback,
        e.status = 'pending_review'
    MERGE (s)-[:HAS_ENSEMBLE_RESULT]->(e)
    """
    params = {
        "answer_id": _generate_answer_id(state),
        "student_answer": state["student_answer"],
        "question": state["question"],
        "ensemble_score": state.get("ensemble_score"),
        "ensemble_feedback": state.get("ensemble_feedback"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _neo4j_query(cypher, params)


def _save_final_result(state: GradingState) -> None:
    """
    최종 채점 결과를 Neo4j 그래프에 영구 저장
    노드: StudentAnswer → EnsembleResult → TeacherReview → FinalScore
    엣지: EVALUATED_BY (각 LLM 모델별)
    """
    if not _HAS_NEO4J or _neo4j_driver is None:
        logger.debug("[Node4] Neo4j 비활성화 — 최종 저장 스킵")
        return

    answer_id = _generate_answer_id(state)

    # 최종 결과 노드 저장
    cypher = """
    MATCH (e:EnsembleResult {answer_id: $answer_id})
    SET e.status = 'finalized'
    MERGE (tr:TeacherReview {answer_id: $answer_id})
    SET tr.approved = $approved,
        tr.correction_note = $correction_note,
        tr.reviewed_at = $timestamp
    MERGE (fs:FinalScore {answer_id: $answer_id})
    SET fs.score = $final_score,
        fs.feedback = $final_feedback,
        fs.total_score = $total_score
    MERGE (e)-[:REVIEWED_BY]->(tr)
    MERGE (tr)-[:DETERMINED]->(fs)
    """
    correction = state.get("teacher_correction") or {}
    params = {
        "answer_id": answer_id,
        "approved": state.get("teacher_approved", False),
        "correction_note": correction.get("correction_note", ""),
        "final_score": state.get("final_score"),
        "final_feedback": state.get("final_feedback"),
        "total_score": state["total_score"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _neo4j_query(cypher, params)

    # 각 평가 모델 결과를 엣지로 저장
    for result in state.get("evaluator_results", []):
        model_cypher = """
        MATCH (e:EnsembleResult {answer_id: $answer_id})
        MERGE (m:LLMEvaluator {name: $model_name})
        MERGE (e)-[r:EVALUATED_BY {answer_id: $answer_id}]->(m)
        SET r.score = $score, r.feedback = $feedback
        """
        _neo4j_query(model_cypher, {
            "answer_id": answer_id,
            "model_name": result["model_name"],
            "score": result["total_score"],
            "feedback": result["feedback"],
        })

    logger.info("[Node4] Neo4j 최종 저장 완료 — answer_id: %s", answer_id)


def _neo4j_query(cypher: str, params: dict) -> None:
    try:
        with _neo4j_driver.session() as session:
            session.run(cypher, **params)
    except Exception as e:
        logger.error("[Node4] Neo4j 쿼리 실패: %s", e)


def _generate_answer_id(state: GradingState) -> str:
    """학생 답안 해시 기반 고유 ID 생성"""
    import hashlib
    content = f"{state['question'][:50]}|{state['student_answer'][:50]}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ── 개발/테스트용 Mock ────────────────────────────────────────────────────────
def _mock_teacher_input(state: GradingState) -> dict:
    """
    개발 환경에서 교사 입력을 시뮬레이션.
    실제 배포 시 LangGraph interrupt() 반환값으로 교체.
    """
    logger.debug("[Node4] Mock 교사 입력 사용 (개발 모드)")
    return {
        "approved": True,          # True: 승인, False: 수정
        "corrected_score": None,   # 수정 점수 (approved=False 시 사용)
        "corrected_feedback": None,
        "correction_note": "",
    }
