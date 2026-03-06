"""
FastAPI 서버: LangGraph 채점 파이프라인 HTTP/SSE API 노출

엔드포인트:
  POST /api/generate-rubric  — Node 1만 실행, JSON 루브릭 반환
  GET  /api/grade-stream     — Node 1-3 SSE 스트리밍 + HITL 대기
  POST /api/hitl-decision    — 교사 승인/수정 → final_score 반환
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── 경로 설정 및 시크릿 로드 ──────────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

# 로깅 설정을 가장 먼저 (이후 임포트되는 모듈들의 경고 로그 포착)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")

# .env.enc 복호화 → os.environ 주입 (GRADING_MASTER_KEY 필요)
from api.secrets import load_secrets
load_secrets()

# ── 필수 API 키 검증 ──────────────────────────────────────────────────────────
def _check_api_keys() -> None:
    """서버 시작 시 필수 환경변수 확인. 없으면 경고 출력."""
    logger = logging.getLogger(__name__)
    missing = []
    optional_missing = []

    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if not os.environ.get("OPENAI_API_KEY"):
        optional_missing.append("OPENAI_API_KEY (선택 — GPT 평가 비활성화)")
    if not os.environ.get("GOOGLE_API_KEY"):
        optional_missing.append("GOOGLE_API_KEY (선택 — Gemini 평가 비활성화)")

    if missing:
        logger.error("필수 환경변수 누락: %s", ", ".join(missing))
        logger.error("터미널에서 다음 명령어를 실행하세요:")
        for key in missing:
            logger.error("  export %s=<your-key>", key)
        raise RuntimeError(f"필수 환경변수 누락: {', '.join(missing)}")

    if optional_missing:
        for msg in optional_missing:
            logger.warning("선택 환경변수 미설정: %s", msg)

    logger.info("API 키 확인 완료 ✓")

from grading_pipeline.nodes.rubric_generator import rubric_generator_node
from grading_pipeline.nodes.rule_based_router import rule_based_router_node
from grading_pipeline.nodes.ensemble_evaluator import ensemble_evaluator_node
from grading_pipeline.state import GradingState, initial_state

logger = logging.getLogger(__name__)

app = FastAPI(title="AI 채점 파이프라인 API", version="1.0.0")


@app.on_event("startup")
async def startup_event() -> None:
    """서버 시작 시 환경변수 검증"""
    _check_api_keys()

# ── CORS 설정 (Next.js dev server 허용) ─────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 인메모리 세션 저장소 ──────────────────────────────────────────────────────
# hitl-decision 호출 시까지 채점 상태 유지
SESSIONS: dict[str, GradingState] = {}


# ── Pydantic 스키마 ───────────────────────────────────────────────────────────
class GenerateRubricRequest(BaseModel):
    subject: str = "auto"
    question: str
    model_answer: str
    total_score: int


class HitlDecisionRequest(BaseModel):
    thread_id: str
    approved: bool
    corrected_score: Optional[float] = None
    corrected_feedback: Optional[str] = None
    correction_note: str = ""


# ── SSE 헬퍼 ─────────────────────────────────────────────────────────────────
def _sse(event_type: str, data: Any) -> str:
    """SSE 이벤트 포맷으로 직렬화"""
    payload = json.dumps({"type": event_type, **({} if not isinstance(data, dict) else data)}
                         if isinstance(data, dict) else
                         {"type": event_type, "message": data},
                         ensure_ascii=False)
    return f"data: {payload}\n\n"


def _sse_progress(message: str, step: int, total_steps: int = 4) -> str:
    """진행률 포함 progress 이벤트"""
    progress = int((step / total_steps) * 100)
    return _sse("progress", {"message": message, "step": step, "progress": progress})


# ── 엔드포인트 1: 루브릭 생성 ─────────────────────────────────────────────────
@app.post("/api/generate-rubric")
async def generate_rubric(req: GenerateRubricRequest) -> dict:
    """Node 1만 실행하여 루브릭 JSON 반환"""
    state = initial_state(
        question=req.question,
        model_answer=req.model_answer,
        student_answer="",  # 루브릭 생성에는 불필요
        total_score=req.total_score,
        subject_tag=req.subject,
    )

    result = rubric_generator_node(state)

    if result.get("error_message"):
        raise HTTPException(status_code=500, detail=result["error_message"])

    return {"rubric": result["rubric"]}


# ── 엔드포인트 2: 채점 SSE 스트리밍 ──────────────────────────────────────────
@app.get("/api/grade-stream")
async def grade_stream(
    subject: str = Query(default="auto"),
    question: str = Query(...),
    model_answer: str = Query(...),
    student_answer: str = Query(...),
    total_score: int = Query(...),
    rubric_json: Optional[str] = Query(default=None),  # 교사가 수정한 루브릭 (JSON 문자열)
) -> StreamingResponse:
    """Node 1-3 순차 실행하며 SSE 스트리밍, HITL 단계에서 대기"""
    thread_id = str(uuid.uuid4())

    async def stream() -> AsyncGenerator[str, None]:
        state = initial_state(
            question=question,
            model_answer=model_answer,
            student_answer=student_answer,
            total_score=total_score,
            subject_tag=subject,
        )

        # thread_id 전달
        yield _sse("started", {"thread_id": thread_id})

        # ── Node 1: 루브릭 생성 ─────────────────────────────────────────────
        if rubric_json:
            # 교사가 이미 루브릭을 수정한 경우 재사용
            try:
                state = {**state, "rubric": json.loads(rubric_json)}
                yield _sse_progress("루브릭 적용 완료 (교사 수정본)", step=1)
            except json.JSONDecodeError:
                yield _sse("error", {"message": "루브릭 JSON 파싱 실패"})
                return
        else:
            yield _sse_progress("루브릭 생성 중...", step=0, total_steps=4)
            state = rubric_generator_node(state)
            if state.get("error_message"):
                yield _sse("error", {"message": state["error_message"]})
                return
            yield _sse_progress("루브릭 생성 완료", step=1)

        yield _sse("rubric_done", {"rubric": state["rubric"]})

        # ── Node 2: Rule-base 라우팅 ────────────────────────────────────────
        yield _sse_progress("Rule-base 엔진 분석 중...", step=1)
        state = rule_based_router_node(state)
        if state.get("error_message"):
            logger.warning("Rule-base 오류 (폴백 계속): %s", state["error_message"])
            # 오류여도 앙상블은 계속 진행
            state = {**state, "error_message": None}
        yield _sse_progress("Rule-base 분석 완료", step=2)
        yield _sse("rule_done", {"rule_metadata": state.get("rule_metadata")})

        # ── Node 3: Ensemble Evaluator ──────────────────────────────────────
        yield _sse_progress("LLM 독립 평가 중...", step=2)
        state = ensemble_evaluator_node(state)
        if state.get("error_message"):
            yield _sse("error", {"message": state["error_message"]})
            return
        yield _sse_progress("의견 조율 완료", step=3)

        # ── HITL: 세션에 상태 저장 후 교사 대기 ────────────────────────────
        SESSIONS[thread_id] = state

        # 모델별 세부 결과 (criterion_scores + original_llm_total 포함)
        evaluator_details = [
            {
                "model_name": r["model_name"],
                "total_score": r["total_score"],
                "original_llm_total": r.get("original_llm_total"),
                "feedback": r["feedback"],
                "criterion_scores": r.get("criterion_scores", []),
            }
            for r in state.get("evaluator_results", [])
        ]

        rule_meta = state.get("rule_metadata") or {}
        yield _sse("hitl_ready", {
            "thread_id": thread_id,
            "ensemble_score": state["ensemble_score"],
            "ensemble_feedback": state["ensemble_feedback"],
            "grand_total": state.get("grand_total"),
            "rule_base_total": rule_meta.get("rule_base_total", 0),
            "per_criterion_rule_scores": rule_meta.get("per_criterion_rule_scores", {}),
            "total_score": total_score,
            "evaluator_results": evaluator_details,
            "debate_log": state.get("debate_log", []),
            "rule_metadata": rule_meta,
        })

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── 엔드포인트 3: HITL 교사 결정 ─────────────────────────────────────────────
@app.post("/api/hitl-decision")
async def hitl_decision(req: HitlDecisionRequest) -> dict:
    """교사 승인/수정 → final_score, final_feedback 반환"""
    state = SESSIONS.get(req.thread_id)
    if state is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다. 채점을 다시 시작하세요.")

    # 교사 결정 처리
    if req.approved:
        # 승인: 앙상블 결과 그대로 확정
        final_score = state["ensemble_score"]
        final_feedback = state["ensemble_feedback"]
        teacher_approved = True
        teacher_correction = None
    else:
        # 수정: 교사 입력값 사용
        final_score = req.corrected_score if req.corrected_score is not None else state["ensemble_score"]
        final_feedback = req.corrected_feedback if req.corrected_feedback else state["ensemble_feedback"]
        teacher_approved = False
        teacher_correction = {
            "corrected_score": req.corrected_score,
            "corrected_feedback": req.corrected_feedback,
            "correction_note": req.correction_note,
        }

    # 세션 상태 업데이트
    final_state = {
        **state,
        "teacher_approved": teacher_approved,
        "teacher_correction": teacher_correction,
        "final_score": final_score,
        "final_feedback": final_feedback,
    }
    SESSIONS[req.thread_id] = final_state

    logger.info(
        "HITL 결정 완료 — thread_id=%s, approved=%s, final_score=%.1f",
        req.thread_id, req.approved, final_score,
    )

    return {
        "thread_id": req.thread_id,
        "teacher_approved": teacher_approved,
        "final_score": final_score,
        "final_feedback": final_feedback,
    }


# ── 헬스체크 ─────────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "sessions": len(SESSIONS),
        "api_keys": {
            "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "openai": bool(os.environ.get("OPENAI_API_KEY")),
            "google": bool(os.environ.get("GOOGLE_API_KEY")),
        },
    }
