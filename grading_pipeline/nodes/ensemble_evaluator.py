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
# NOTE: 패키지 미설치 또는 API 키 미설정 시 해당 모델 비활성화 (서버 시작은 계속 진행)
import os as _os

try:
    from langchain_openai import ChatOpenAI
    if _os.environ.get("OPENAI_API_KEY"):
        _gpt = ChatOpenAI(model="gpt-4o-mini", temperature=0.2, max_tokens=4096)
        _HAS_GPT = True
    else:
        _HAS_GPT = False
        logger.warning("OPENAI_API_KEY 미설정 — GPT 평가 비활성화")
except ImportError:
    _HAS_GPT = False
    logger.warning("langchain_openai 미설치 — GPT 평가 비활성화")

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    if _os.environ.get("GOOGLE_API_KEY"):
        _gemini = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.2)
        _HAS_GEMINI = True
    else:
        _HAS_GEMINI = False
        logger.warning("GOOGLE_API_KEY 미설정 — Gemini 평가 비활성화")
except ImportError:
    _HAS_GEMINI = False
    logger.warning("langchain_google_genai 미설치 — Gemini 평가 비활성화")

# Anthropic 모델은 항상 사용 (ANTHROPIC_API_KEY는 server.py startup에서 필수 검증)
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


# ── Rule-base 10% / LLM 90% 기준별 점수 조정 ────────────────────────────────
def _adjust_criterion_scores(
    evaluator_results: list[EvaluatorResult],
    per_criterion_rule_scores: dict[str, float],
    rubric: dict,
) -> list[EvaluatorResult]:
    """
    각 평가 결과의 기준별 점수를 LLM 90% + Rule-base 10%로 조정.

    조정식: adjusted_ratio = 0.9 × (llm_score / max_score) + 0.1 × rule_ratio
            adjusted_score = adjusted_ratio × max_score
    """
    max_scores: dict[str, float] = {
        item["criterion_id"]: float(item["max_score"])
        for item in rubric.get("rubric_items", [])
    }

    adjusted: list[EvaluatorResult] = []
    for result in evaluator_results:
        new_criterion_scores = []
        for cs in result["criterion_scores"]:
            cid = cs["criterion_id"]
            max_s = max_scores.get(cid, 1.0)
            llm_ratio = cs["score"] / max_s if max_s > 0 else 0.0
            rule_ratio = per_criterion_rule_scores.get(cid, 0.0)
            adjusted_ratio = 0.9 * llm_ratio + 0.1 * rule_ratio
            adjusted_score = round(adjusted_ratio * max_s, 2)
            new_criterion_scores.append({
                **cs,
                "score": adjusted_score,
                "original_llm_score": cs["score"],
                "rule_ratio": round(rule_ratio, 4),
                "rationale": cs["rationale"],
            })

        adjusted_total = round(sum(c["score"] for c in new_criterion_scores), 2)
        adjusted.append({
            **result,
            "criterion_scores": new_criterion_scores,
            "total_score": adjusted_total,
            "original_llm_total": result["total_score"],
        })
    return adjusted


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
    per_criterion_rule_scores: dict[str, float],
    rule_base_total: float,
) -> tuple[float, str]:
    """가중 평균 점수 + 최종 피드백 생성"""
    total_score = state["rubric"]["total_score"]
    threshold_str = str(_DEBATE_THRESHOLD)

    # rule-base 감점 항목 정리 (점수 < 1.0)
    rubric_items_by_id = {
        item["criterion_id"]: item.get("description", item["criterion_id"])
        for item in state["rubric"].get("rubric_items", [])
    }
    rule_base_info = {
        "per_criterion": {
            cid: {
                "score": score,
                "description": rubric_items_by_id.get(cid, cid),
                "deducted": score < 1.0,
            }
            for cid, score in per_criterion_rule_scores.items()
        },
        "rule_base_total": round(rule_base_total, 2),
        "max_possible": len(per_criterion_rule_scores),
    }

    aggregator_user = AGGREGATOR_USER.format(
        total_score=total_score,
        rule_base_info=json.dumps(rule_base_info, ensure_ascii=False, indent=2),
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

    # rule-base per-criterion 점수 수집
    rule_metadata = state.get("rule_metadata") or {}
    per_criterion_rule_scores: dict[str, float] = rule_metadata.get("per_criterion_rule_scores") or {}
    rule_base_total: float = rule_metadata.get("rule_base_total") or 0.0
    rubric = state.get("rubric") or {}

    # 1. 병렬 평가
    try:
        evaluator_results = _run_parallel_evaluators(state)
    except RuntimeError as e:
        return {**state, "error_message": str(e)}

    # 2. Rule-base 10% / LLM 90% 기준별 점수 조정
    if per_criterion_rule_scores and rubric:
        adjusted_results = _adjust_criterion_scores(
            evaluator_results, per_criterion_rule_scores, rubric
        )
    else:
        adjusted_results = evaluator_results  # rule-base 없으면 원본 유지

    # 3. 편차 분석 → Debate (조정된 점수 기준)
    scores = [r["total_score"] for r in adjusted_results]
    total_std = statistics.stdev(scores) if len(scores) > 1 else 0.0
    logger.info("[Node3] 심사위원 총점 표준편차(조정후): %.2f", total_std)

    debate_log: list[str] = []
    if total_std > _DEBATE_THRESHOLD:
        logger.info("[Node3] 점수 편차 초과 — Debate 체인 가동")
        high_var = _detect_high_variance_criteria(adjusted_results)
        debate_log = _run_debate(adjusted_results, high_var)

    # 4. 최종 집계 (ensemble_score = Part 2)
    try:
        ensemble_score, ensemble_feedback = _aggregate(
            adjusted_results, state, per_criterion_rule_scores, rule_base_total
        )
    except Exception as e:
        logger.error("[Node3] Aggregator 실패: %s", e)
        ensemble_score = round(sum(scores) / len(scores), 1)
        ensemble_feedback = "\n\n".join(r["feedback"] for r in adjusted_results)

    # 5. grand_total = Part1(rule_base_total) + Part2(ensemble_score)
    grand_total = round(rule_base_total + ensemble_score, 2)

    logger.info(
        "[Node3] 최종 점수: ensemble=%.1f + rule_base=%.2f = grand_total=%.2f (최대 %d+%d)",
        ensemble_score, rule_base_total, grand_total,
        state["total_score"], len(per_criterion_rule_scores),
    )

    return {
        **state,
        "evaluator_results": adjusted_results,
        "debate_log": debate_log,
        "ensemble_score": ensemble_score,
        "ensemble_feedback": ensemble_feedback,
        "grand_total": grand_total,
    }


def _strip_code_block(text: str) -> str:
    """LLM 응답에서 ```json ... ``` 블록 제거"""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
    return s.strip()
