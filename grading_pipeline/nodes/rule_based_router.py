"""
Node 2: Rule-based Router
루브릭의 과목 태그 또는 자동 감지 결과에 따라
결정론적 Rule-base 엔진을 통과시켜 메타데이터 추출

라우팅 결정:
  "math"    → SymPy 수식 동치성 검증 + 키워드
  "korean"  → Sentence-BERT 의미 유사도 + Kiwipiepy 형태소 + 키워드
  "science" → Sentence-BERT 의미 유사도 + 인과 구조 + 키워드
  "general" → 키워드 매칭 기반 단순 검사
"""
from __future__ import annotations

import logging
import re
from typing import Literal

from grading_pipeline.engines.math_verifier import verify_math
from grading_pipeline.engines.nlp_engine import score_korean, score_science
from grading_pipeline.state import GradingState, RuleMetadata

logger = logging.getLogger(__name__)

SubjectTag = Literal["math", "korean", "science", "general"]

# 수학 문항 자동 감지 패턴 (수식 기호 포함 시 math로 분류)
_MATH_PATTERNS = re.compile(
    r"[=\+\-\*\/\^\(\)]|sqrt|log|sin|cos|tan|lim|∫|∑|∏|≤|≥|±"
)

# "또는", "or", "," 로 구분된 다중 해 패턴
_MULTI_SOL_SEP = re.compile(r"\s*(?:또는|혹은|,|or)\s*", re.IGNORECASE)

# 단순 수식/방정식 패턴 (알파벳 변수 포함)
_SIMPLE_EXPR = re.compile(
    r"[a-zA-Z]\s*=\s*-?[\d\.\s\+\-\*\/\(\)\^a-zA-Z]+"  # x = ..., y = ...
    r"|[a-zA-Z0-9\(\)\+\-\*\/\^\s]+=\s*[a-zA-Z0-9\(\)\+\-\*\/\^\s]+"  # 등식
)

# 한국어 제거 (조사, 어미, 한글 문자 전체)
_KOR_STRIP = re.compile(r"[가-힣]+")


def _clean_expr(s: str) -> str:
    """수식 후보에서 한국어·특수기호 제거 후 정제"""
    s = _KOR_STRIP.sub(" ", s).strip()
    s = re.sub(r"\s{2,}", " ", s).strip()
    # 앞뒤 비수식 문자 제거
    s = re.sub(r"^[\s,;:·]+|[\s,;:·]+$", "", s)
    return s


def _extract_math_expressions(text: str) -> list[str]:
    """
    자연어 답안에서 SymPy 파싱 가능한 수식 후보 목록을 추출.

    우선순위:
    1. '따라서', '이므로', '∴' 뒤의 결론 문장 → "또는"/"," 기준으로 분리
    2. 텍스트 전체에서 단순 수식 패턴 추출
    """
    candidates: list[str] = []

    # 1단계: 결론 지시어 뒤 텍스트 추출
    conclusion_re = re.compile(
        r"(?:따라서|이므로|∴|결론|답)\s*[:\s]*(.+?)(?:\.|$)", re.MULTILINE
    )
    for m in conclusion_re.finditer(text):
        segment = m.group(1).strip()
        # "또는", "," 로 분리된 다중 해를 개별 후보로
        for part in _MULTI_SOL_SEP.split(segment):
            cleaned = _clean_expr(part)
            if cleaned:
                candidates.append(cleaned)

    # 2단계: 단순 수식 패턴 전체 검색 (보완)
    for m in _SIMPLE_EXPR.finditer(text):
        cleaned = _clean_expr(m.group())
        if cleaned:
            candidates.append(cleaned)

    # 중복 제거 + 길이 필터
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        if len(c) >= 2 and c not in seen:
            seen.add(c)
            result.append(c)
    return result


def rule_based_router_node(state: GradingState) -> GradingState:
    """
    LangGraph Node 2: Rule-based Router

    입력 상태 필드: rubric, student_answer, model_answer, subject_tag
    출력 상태 필드: rule_metadata, route
    """
    logger.info("[Node2] Rule-based Router 시작")

    tag = _resolve_subject_tag(state)
    logger.info("[Node2] 라우팅 결정: %s", tag)

    try:
        if tag == "math":
            metadata = _math_engine(state)
        elif tag == "korean":
            metadata = _korean_engine(state)
        elif tag == "science":
            metadata = _science_engine(state)
        else:
            metadata = _general_engine(state)

        return {**state, "rule_metadata": metadata, "route": tag}

    except Exception as e:
        logger.exception("[Node2] Rule-base 엔진 오류")
        return {**state, "error_message": f"Rule-base 오류: {e}", "route": "general"}


# ── 과목 태그 결정 ─────────────────────────────────────────────────────────────
def _resolve_subject_tag(state: GradingState) -> SubjectTag:
    """
    1) 사용자 명시 subject_tag가 "auto"가 아니면 그대로 사용
    2) 루브릭의 첫 번째 항목 키워드로 추론
    3) 모범 답안 텍스트에서 수식 패턴 감지
    """
    explicit = state.get("subject_tag", "auto")
    if explicit and explicit != "auto":
        return explicit  # type: ignore[return-value]

    # 루브릭 키워드에서 과목 추론
    rubric = state.get("rubric") or {}
    keywords_all: list[str] = []
    for item in rubric.get("rubric_items", []):
        keywords_all.extend(item.get("keywords", []))
    keywords_text = " ".join(keywords_all).lower()

    if any(k in keywords_text for k in ["수식", "방정식", "함수", "미분", "적분", "행렬"]):
        return "math"
    if any(k in keywords_text for k in ["주제", "서술", "논지", "문단", "어휘"]):
        return "korean"
    if any(k in keywords_text for k in ["반응", "원소", "세포", "에너지", "힘", "파동"]):
        return "science"

    # 텍스트 수식 패턴 감지
    model_ans = state.get("model_answer", "")
    if _MATH_PATTERNS.search(model_ans):
        return "math"

    return "general"


# ── 수학 엔진 ─────────────────────────────────────────────────────────────────
def _math_engine(state: GradingState) -> RuleMetadata:
    """
    SymPy 수식 동치성 검증 + 키워드 적중률 → 가중 합산 점수

    점수 산출:
      - 수식 동치성 (가중치 60%): 학생 답안에서 수식 후보 추출 후 SymPy 검증
      - 키워드 적중률 (가중치 40%): 루브릭 키워드가 학생 답안에 포함되는지 확인
      단, 수식 파싱 자체가 불가능하면 키워드 100%로 대체
    """
    student_full = state["student_answer"].strip()
    model_ans = state["model_answer"].strip()
    rubric = state.get("rubric") or {}
    total = float(rubric.get("total_score", 0))

    errors: list[dict] = []
    keyword_hits: list[str] = []
    keyword_misses: list[str] = []

    # ── 수식 동치성 검증 ──────────────────────────────────────────────────────
    # 전체 자연어 텍스트 대신 답안에서 수식 후보를 추출해 시도
    math_equiv = None
    math_equiv_score_ratio = 0.0  # 0.0 ~ 1.0
    parse_attempted = False

    candidates = _extract_math_expressions(student_full)
    # 후보가 없으면 전체 텍스트 그대로 시도 (순수 수식 답안 대비)
    if not candidates:
        candidates = [student_full]

    # 모범 답안도 동일하게 후보 추출 (한국어 혼재 대비)
    model_candidates = _extract_math_expressions(model_ans) or [model_ans]

    for candidate in candidates:
        for model_cand in model_candidates:
            result = verify_math(candidate, model_cand)
            if result.method != "error":  # 파싱 성공
                parse_attempted = True
                math_equiv = result.to_dict()
                math_equiv_score_ratio = 1.0 if result.is_equivalent else 0.0
                if not result.is_equivalent:
                    errors.append({
                        "type": "MathEquivalenceError",
                        "span": candidate,
                        "message": (
                            f"수식이 모범 답안과 동치가 아닙니다. "
                            f"(방법: {result.method}, diff: {result.algebraic_diff})"
                        ),
                    })
                break
        if parse_attempted:
            break

    if not parse_attempted:
        # 모든 후보 파싱 실패 → 키워드 분석으로 대체
        errors.append({
            "type": "ParseError",
            "span": student_full[:80],
            "message": "답안에서 수식을 추출할 수 없어 키워드 분석으로 대체합니다.",
        })

    # ── 키워드 적중률 검사 (모범 답안 기반 루브릭 키워드) ─────────────────────
    hit_score = 0.0
    for item in rubric.get("rubric_items", []):
        item_keywords: list[str] = item.get("keywords", [])
        item_max: int = item.get("max_score", 0)
        item_hits = [kw for kw in item_keywords if kw.lower() in student_full.lower()]
        item_misses = [kw for kw in item_keywords if kw.lower() not in student_full.lower()]
        keyword_hits.extend(item_hits)
        keyword_misses.extend(item_misses)
        if item_keywords:
            hit_score += item_max * (len(item_hits) / len(item_keywords))
        else:
            hit_score += item_max  # 키워드 없는 기준은 만점 처리

    keyword_score_ratio = hit_score / total if total > 0 else 0.0

    # ── 가중 합산 점수 ────────────────────────────────────────────────────────
    if math_equiv is not None:
        # 수식 파싱 성공: 동치성 60% + 키워드 40%
        rule_score = total * (0.6 * math_equiv_score_ratio + 0.4 * keyword_score_ratio)
    else:
        # 수식 파싱 실패: 키워드 100%
        rule_score = total * keyword_score_ratio

    return RuleMetadata(
        subject_tag="math",
        rule_score=round(rule_score, 2),
        rule_max_score=total,
        errors=errors,
        math_equivalence=math_equiv,
        keyword_hits=keyword_hits,
        keyword_misses=keyword_misses,
    )


# ── 국어 엔진 (Stub — KoNLPy / LSA 통합 예정) ────────────────────────────────
def _korean_engine(state: GradingState) -> RuleMetadata:
    """
    국어 논술 엔진:
      - 의미적 유사도 (SBERT, 모범답안 기준)  : 30%
      - 루브릭 기준 커버리지 (SBERT, 기준별)  : 50%
      - 논리적 구조 표현 점수                : 20%

    키워드 정확 매칭·형태소 겹침률 제거.
    키워드는 여전히 참고 지표로 표시하되 점수에는 미반영.
    """
    logger.info("[Node2] 국어 엔진 시작 (SBERT 기준 커버리지 + 논리 구조)")
    student_text = state["student_answer"].strip()
    model_text = state["model_answer"].strip()
    rubric = state.get("rubric") or {}
    total = float(rubric.get("total_score", 0))
    rubric_items = rubric.get("rubric_items", [])

    # 키워드는 참고 표시용으로만 수집 (점수에 미반영)
    keyword_hits, keyword_misses, _ = _calc_keyword_stats(state)
    errors = _keyword_miss_errors(keyword_misses)

    score_ratio, nlp_details = score_korean(student_text, model_text, rubric_items)
    rule_score = round(total * score_ratio, 2)

    logger.info(
        "[Node2] 국어 점수: %.2f / %.0f (sem=%.2f, cov=%.2f, disc=%.2f)",
        rule_score, total,
        nlp_details["semantic_similarity"],
        nlp_details["criterion_coverage"],
        nlp_details["discourse_structure"],
    )

    return RuleMetadata(
        subject_tag="korean",
        rule_score=rule_score,
        rule_max_score=total,
        errors=errors,
        math_equivalence=nlp_details,  # nlp_details를 확장 필드로 재활용
        keyword_hits=keyword_hits,
        keyword_misses=keyword_misses,
    )


# ── 과학 엔진 ─────────────────────────────────────────────────────────────────
def _science_engine(state: GradingState) -> RuleMetadata:
    """
    과학 엔진:
      - Sentence-BERT 의미적 유사도 40%
      - Kiwipiepy 형태소 내용어 겹침률 20%
      - 루브릭 키워드 적중률 25%
      - 인과·논리 구조 표현 점수 15%
    """
    logger.info("[Node2] 과학 엔진 시작 (Sentence-BERT + 인과구조)")
    student_text = state["student_answer"].strip()
    model_text = state["model_answer"].strip()
    rubric = state.get("rubric") or {}
    total = float(rubric.get("total_score", 0))

    keyword_hits, keyword_misses, keyword_hit_ratio = _calc_keyword_stats(state)
    errors = _keyword_miss_errors(keyword_misses)

    score_ratio, nlp_details = score_science(student_text, model_text, keyword_hit_ratio)
    rule_score = round(total * score_ratio, 2)

    logger.info(
        "[Node2] 과학 점수: %.2f / %.0f (sem=%.2f, morph=%.2f, causal=%.2f, kw=%.2f)",
        rule_score, total,
        nlp_details["semantic_similarity"],
        nlp_details["morpheme_overlap"],
        nlp_details["causal_structure_score"],
        nlp_details["keyword_hit_ratio"],
    )

    return RuleMetadata(
        subject_tag="science",
        rule_score=rule_score,
        rule_max_score=total,
        errors=errors,
        math_equivalence=nlp_details,
        keyword_hits=keyword_hits,
        keyword_misses=keyword_misses,
    )


# ── 일반 엔진 ─────────────────────────────────────────────────────────────────
def _general_engine(state: GradingState) -> RuleMetadata:
    return _keyword_matching(state, subject_tag="general")


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────

def _calc_keyword_stats(state: GradingState) -> tuple[list[str], list[str], float]:
    """루브릭 키워드 적중/누락 및 적중률 계산. (hits, misses, hit_ratio) 반환"""
    student_lower = state["student_answer"].lower()
    rubric = state.get("rubric") or {}
    total = float(rubric.get("total_score", 0))

    hits: list[str] = []
    misses: list[str] = []
    hit_score = 0.0

    for item in rubric.get("rubric_items", []):
        item_keywords: list[str] = item.get("keywords", [])
        item_max: int = item.get("max_score", 0)
        item_hits = [kw for kw in item_keywords if kw.lower() in student_lower]
        item_misses = [kw for kw in item_keywords if kw.lower() not in student_lower]
        hits.extend(item_hits)
        misses.extend(item_misses)
        if item_keywords:
            hit_score += item_max * (len(item_hits) / len(item_keywords))
        else:
            hit_score += item_max

    hit_ratio = (hit_score / total) if total > 0 else 0.0
    return hits, misses, hit_ratio


def _keyword_miss_errors(keyword_misses: list[str]) -> list[dict]:
    return [
        {"type": "KeywordMissing", "span": "", "message": f"핵심어 누락: {kw}"}
        for kw in keyword_misses
    ]


# ── 공통 키워드 매칭 헬퍼 (general / 폴백) ────────────────────────────────────
def _keyword_matching(state: GradingState, subject_tag: str) -> RuleMetadata:
    rubric = state.get("rubric") or {}
    total = float(rubric.get("total_score", 0))

    keyword_hits, keyword_misses, hit_ratio = _calc_keyword_stats(state)
    errors = _keyword_miss_errors(keyword_misses)
    rule_score = round(total * hit_ratio, 2)

    return RuleMetadata(
        subject_tag=subject_tag,
        rule_score=rule_score,
        rule_max_score=total,
        errors=errors,
        math_equivalence=None,
        keyword_hits=keyword_hits,
        keyword_misses=keyword_misses,
    )
