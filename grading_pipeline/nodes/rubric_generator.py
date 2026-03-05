"""
Node 1: Rubric Generator
교사 입력(문항 + 모범 답안)을 받아 Bloom's Taxonomy 기반 JSON 루브릭 생성
사용 모델: Claude Opus 4.6 (가장 높은 추론 능력 요구)
"""
from __future__ import annotations

import json
import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from grading_pipeline.prompts import RUBRIC_GENERATOR_SYSTEM, RUBRIC_GENERATOR_USER
from grading_pipeline.state import GradingState, Rubric

logger = logging.getLogger(__name__)

# Claude Opus 4.6 — 루브릭 설계는 고품질 추론 필요
_llm = ChatAnthropic(
    model="claude-opus-4-6",
    temperature=0.1,          # 루브릭은 결정론적 출력 선호
    max_tokens=2048,
)


def rubric_generator_node(state: GradingState) -> GradingState:
    """
    LangGraph Node 1: Rubric Generator

    입력 상태 필드: question, model_answer, total_score
    출력 상태 필드: rubric
    """
    logger.info("[Node1] Rubric Generator 시작")

    question_and_answer = (
        f"[문항]\n{state['question']}\n\n"
        f"[모범 답안]\n{state['model_answer']}"
    )
    user_content = RUBRIC_GENERATOR_USER.format(
        question_and_answer=question_and_answer,
        total_score=state["total_score"],
    )

    messages = [
        SystemMessage(content=RUBRIC_GENERATOR_SYSTEM),
        HumanMessage(content=user_content),
    ]

    try:
        response = _llm.invoke(messages)
        raw = response.content.strip()

        # 코드 블록 제거 (```json ... ```)
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        rubric_dict: dict = json.loads(raw)
        _validate_rubric(rubric_dict, state["total_score"])

        logger.info("[Node1] 루브릭 생성 완료 — 기준 수: %d", len(rubric_dict["rubric_items"]))
        return {**state, "rubric": rubric_dict}

    except json.JSONDecodeError as e:
        logger.error("[Node1] JSON 파싱 실패: %s", e)
        return {**state, "error_message": f"루브릭 JSON 파싱 오류: {e}"}
    except ValueError as e:
        logger.error("[Node1] 루브릭 검증 실패: %s", e)
        return {**state, "error_message": str(e)}
    except Exception as e:
        logger.exception("[Node1] 예상치 못한 오류")
        return {**state, "error_message": f"루브릭 생성 오류: {e}"}


def _validate_rubric(rubric: dict, expected_total: int) -> None:
    """루브릭 JSON 구조 및 배점 합계 검증"""
    required_keys = {"task_description", "cognitive_level", "total_score", "rubric_items"}
    missing = required_keys - set(rubric.keys())
    if missing:
        raise ValueError(f"루브릭에 필수 키 누락: {missing}")

    items: list = rubric["rubric_items"]
    if not items:
        raise ValueError("rubric_items가 비어 있습니다.")

    # 배점 합계 검증
    score_sum = sum(item.get("max_score", 0) for item in items)
    if score_sum != expected_total:
        raise ValueError(
            f"루브릭 배점 합계({score_sum})가 총점({expected_total})과 불일치합니다."
        )

    # criterion_id 중복 검증
    ids = [item.get("criterion_id") for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("criterion_id에 중복 항목이 있습니다.")
