"""
Node 3: Multi-LLM Ensemble Evaluator
3개의 병렬 Evaluator + Aggregator 구조로 앙상블 채점 수행

Evaluator 모델:
  - GPT-5 mini    (OpenAI)
  - Gemini 2.5 Pro (Google)
  - Claude Sonnet 4.6 (Anthropic) — Llama 접근 불가 시 대체

Aggregator:
  - 점수 편차 분석 → Debate 체인 → 가중 평균 → 최종 피드백
"""
from __future__ import annotations

import json
import logging
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from grading_pipeline.prompts import (
    AGGREGATOR_SYSTEM,
    AGGREGATOR_USER,
    DEBATE_SYSTEM,
    EVALUATOR_SYSTEM,
    EVALUATOR_USER,
)
from grading_pipeline.state import EvaluatorResult, GradingState

logger = logging.getLogger(__name__)

# ── 점수 편차 임계값 (표준편차 기준) ─────────────────────────────────────────
_DEBATE_THRESHOLD = 1.5  # 심사위원 간 총점 표준편차가 이 값 초과 시 토론 가동

# ── LLM 클라이언트 초기화 ─────────────────────────────────────────────────────
# NOTE: API 키는 환경변수 ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY로 설정
try:
    from langchain_openai import ChatOpenAI
    _gpt = ChatOpenAI(model="gpt-4o-mini", temperature=0.2, max_tokens=1024)
    _HAS_GPT = True
except ImportError:
    _HAS_GPT = False
    logger.warning("langchain_openai 미설치 — GPT 평가 비활성화")

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    _gemini = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.2)
    _HAS_GEMINI = True
except ImportError:
    _HAS_GEMINI = False
    logger.warning("langchain_google_genai 미설치 — Gemini 평가 비활성화")

# Anthropic 모델은 항상 사용 가능 (Claude Sonnet 4.6)
_claude = ChatAnthropic(model="claude-sonnet-4-6", temperature=0.2, max_tokens=4096)
_claude_aggregator = ChatAnthropic(model="claude-opus-4-6", temperature=0.1, max_tokens=2048)


# ── 단일 Evaluator 호출 ───────────────────────────────────────────────────────
def _call_evaluator(
    llm,
    model_name: str,
    state: GradingState,
) -> EvaluatorResult:
    """단일 LLM 평가 수행. ThreadPoolExecutor에서 병렬 호출됨."""
    user_content = EVALUATOR_USER.format(
        rubric=json.dumps(state["rubric"], ensure_ascii=False, indent=2),
        rule_metadata=json.dumps(state["rule_metadata"], ensure_ascii=False, indent=2),
        student_answer=state["student_answer"],
        model_answer=state["model_answer"],
    )
    messages = [
        SystemMessage(content=EVALUATOR_SYSTEM),
        HumanMessage(content=user_content),
    ]
    response = llm.invoke(messages)
    raw = _strip_code_block(response.content)
    parsed: dict = json.loads(raw)

    return EvaluatorResult(
        model_name=model_name,
        criterion_scores=parsed.get("criterion_scores", []),
        total_score=float(parsed.get("total_score", 0)),
        feedback=parsed.get("feedback", ""),
        raw_response=response.content,
    )


# ── 병렬 평가 실행 ────────────────────────────────────────────────────────────
def _run_parallel_evaluators(state: GradingState) -> list[EvaluatorResult]:
    """사용 가능한 모든 LLM 평가 모델을 병렬 실행"""
    tasks: list[tuple] = [("claude-sonnet-4-6", _claude)]
    if _HAS_GPT:
        tasks.append(("gpt-5-mini", _gpt))
    if _HAS_GEMINI:
        tasks.append(("gemini-2.5-pro", _gemini))

    results: list[EvaluatorResult] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        future_map = {
            executor.submit(_call_evaluator, llm, name, state): name
            for name, llm in tasks
        }
        for future in as_completed(future_map):
            model_name = future_map[future]
            try:
                results.append(future.result())
                logger.info("[Node3] %s 평가 완료 — 점수: %.1f", model_name, results[-1]["total_score"])
            except Exception as e:
                logger.error("[Node3] %s 평가 실패: %s", model_name, e)
                errors.append(f"{model_name}: {e}")

    if not results:
        raise RuntimeError(f"모든 평가 모델 실패: {errors}")
    return results


# ── 편차 분석 및 Debate ───────────────────────────────────────────────────────
def _detect_high_variance_criteria(
    results: list[EvaluatorResult],
    threshold: float = _DEBATE_THRESHOLD,
) -> list[str]:
    """기준별 점수 편차가 큰 criterion_id 목록 반환"""
    from collections import defaultdict

    crit_scores: dict[str, list[float]] = defaultdict(list)
    for r in results:
        for cs in r["criterion_scores"]:
            crit_scores[cs["criterion_id"]].append(float(cs["score"]))

    high_var = [
        cid
        for cid, scores in crit_scores.items()
        if len(scores) > 1 and statistics.stdev(scores) > threshold
    ]
    return high_var


def _run_debate(
    results: list[EvaluatorResult],
    high_var_criteria: list[str],
) -> list[str]:
    """편차가 큰 기준에 대해 Claude Opus로 재조율. 토론 로그 반환."""
    debate_log: list[str] = []
    for cid in high_var_criteria:
        opinions = [
            {"model": r["model_name"], "score": cs["score"], "rationale": cs["rationale"]}
            for r in results
            for cs in r["criterion_scores"]
            if cs["criterion_id"] == cid
        ]
        debate_user = (
            f"기준 ID: {cid}\n\n평가 의견:\n"
            + json.dumps(opinions, ensure_ascii=False, indent=2)
        )
        messages = [
            SystemMessage(content=DEBATE_SYSTEM),
            HumanMessage(content=debate_user),
        ]
        try:
            resp = _claude_aggregator.invoke(messages)
            raw = _strip_code_block(resp.content)
            decision: dict = json.loads(raw)
            debate_log.append(
                f"[Debate:{cid}] 최종 점수={decision.get('decision_score')} "
                f"— {decision.get('decision_rationale', '')}"
            )
        except Exception as e:
            logger.error("[Node3] Debate 실패 (기준 %s): %s", cid, e)
            debate_log.append(f"[Debate:{cid}] 조율 실패: {e}")
    return debate_log


# ── Aggregator ────────────────────────────────────────────────────────────────
def _aggregate(
    results: list[EvaluatorResult],
    state: GradingState,
) -> tuple[float, str]:
    """가중 평균 점수 + 최종 피드백 생성"""
    total_score = state["rubric"]["total_score"]
    threshold_str = str(_DEBATE_THRESHOLD)

    aggregator_user = AGGREGATOR_USER.format(
        total_score=total_score,
        evaluator_results=json.dumps(
            [
                {
                    "model": r["model_name"],
                    "total_score": r["total_score"],
                    "criterion_scores": r["criterion_scores"],
                    "feedback": r["feedback"],
                }
                for r in results
            ],
            ensure_ascii=False,
            indent=2,
        ),
    )
    messages = [
        SystemMessage(content=AGGREGATOR_SYSTEM.format(threshold=threshold_str)),
        HumanMessage(content=aggregator_user),
    ]
    resp = _claude_aggregator.invoke(messages)
    raw = _strip_code_block(resp.content)
    agg: dict = json.loads(raw)

    return float(agg.get("ensemble_score", 0)), agg.get("final_feedback", "")


# ── 메인 노드 함수 ────────────────────────────────────────────────────────────
def ensemble_evaluator_node(state: GradingState) -> GradingState:
    """
    LangGraph Node 3: Ensemble Evaluator

    입력 상태 필드: rubric, rule_metadata, student_answer, model_answer
    출력 상태 필드: evaluator_results, debate_log, ensemble_score, ensemble_feedback
    """
    logger.info("[Node3] Ensemble Evaluator 시작")

    if not state.get("rubric"):
        return {**state, "error_message": "루브릭 없음 — Node1 실패 여부 확인"}

    # 1. 병렬 평가
    try:
        evaluator_results = _run_parallel_evaluators(state)
    except RuntimeError as e:
        return {**state, "error_message": str(e)}

    # 2. 편차 분석 → Debate
    scores = [r["total_score"] for r in evaluator_results]
    total_std = statistics.stdev(scores) if len(scores) > 1 else 0.0
    logger.info("[Node3] 심사위원 총점 표준편차: %.2f", total_std)

    debate_log: list[str] = []
    if total_std > _DEBATE_THRESHOLD:
        logger.info("[Node3] 점수 편차 초과 — Debate 체인 가동")
        high_var = _detect_high_variance_criteria(evaluator_results)
        debate_log = _run_debate(evaluator_results, high_var)

    # 3. 최종 집계
    try:
        ensemble_score, ensemble_feedback = _aggregate(evaluator_results, state)
    except Exception as e:
        logger.error("[Node3] Aggregator 실패: %s", e)
        # 폴백: 단순 평균
        ensemble_score = round(sum(scores) / len(scores), 1)
        ensemble_feedback = "\n\n".join(r["feedback"] for r in evaluator_results)

    logger.info("[Node3] 최종 앙상블 점수: %.1f / %d", ensemble_score, state["total_score"])

    return {
        **state,
        "evaluator_results": evaluator_results,
        "debate_log": debate_log,
        "ensemble_score": ensemble_score,
        "ensemble_feedback": ensemble_feedback,
    }


def _strip_code_block(text: str) -> str:
    """LLM 응답에서 ```json ... ``` 블록 제거"""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
    return s.strip()
