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
from grading_pipeline.engines.nlp_engine import score_korean, score_science, score_keywords_semantic
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
    1. 결론 지시어(따라서/이므로/∴) 앞·뒤 세그먼트 모두 수집
    2. 등식(lhs = rhs) 패턴 전체 검색
    3. 괄호 포함 다항 순수 식 패턴 (등호 없는 인수 형태 포함)
    """
    candidates: list[str] = []
    clean_text = _KOR_STRIP.sub(" ", text)  # 한국어 제거 후 수식만 분석

    # 1단계: 결론 지시어 기준으로 앞·뒤 세그먼트 모두 수집
    conclusion_re = re.compile(
        r"(?:따라서|이므로|∴|결론|답)\s*[:\s]*", re.MULTILINE
    )
    positions = [m.end() for m in conclusion_re.finditer(text)]
    starts = [0] + positions          # 지시어 앞 세그먼트 시작점
    ends = positions + [len(text)]    # 세그먼트 끝점

    for start, end in zip(starts, ends):
        segment = text[start:end]
        for part in _MULTI_SOL_SEP.split(segment):
            cleaned = _clean_expr(part)
            if cleaned:
                candidates.append(cleaned)

    # 2단계: 등식 패턴 (lhs = rhs) 전체 검색
    for m in _SIMPLE_EXPR.finditer(clean_text):
        cleaned = _clean_expr(m.group())
        if cleaned:
            candidates.append(cleaned)

    # 3단계: 괄호 포함 순수 식 패턴 (등호 없는 인수·전개 형태)
    # 예: x(40-2x), -2(x-10)^2+200, -2x^2+40x
    _PURE_EXPR = re.compile(
        r"-?\d*\.?\d*\s*[a-zA-Z]\s*\([^)=]{2,}\)"      # x(...)  형태
        r"|-?\d+\s*\([^)=]{2,}\)\s*\*?\*?\d*"           # 2(...)  형태
        r"|-?\d*\.?\d*\s*[a-zA-Z]\s*(?:\*\*\d+|\^\d+)"  # x^2, x**2 형태
        r"|-?\d+\s*[a-zA-Z]\s*\^?\*?\*?\d*\s*[+\-][\s\d\*a-zA-Z\(\)\^\.\+\-]+"  # 다항 전개
    )
    for m in _PURE_EXPR.finditer(clean_text):
        cleaned = _clean_expr(m.group())
        if cleaned:
            candidates.append(cleaned)

    # 중복 제거 + 길이 필터 (너무 짧은 숫자 단독 후보는 제외)
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        is_only_number = re.fullmatch(r"-?\d+\.?\d*", c)
        if len(c) >= 3 and not is_only_number and c not in seen:
            seen.add(c)
            result.append(c)

    # 순수 숫자 후보는 맨 뒤에 추가 (단독 비교 시 폴백용)
    for c in candidates:
        is_only_number = re.fullmatch(r"-?\d+\.?\d*", c)
        if is_only_number and c not in seen:
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


# ── 기준별 Rule-base 점수 헬퍼 ────────────────────────────────────────────────

def _score_math_per_criterion(
    student_candidates: list[str],
    model_candidates: list[str],
    criterion: dict,
    student_full: str,
) -> float:
    """
    단일 루브릭 기준에 대한 수학 rule-base 점수 (0~1).

    우선순위:
    1. 기준의 keywords에서 수식을 추출 → 학생 후보와 동치 검사
    2. 수식이 없고 keywords만 있으면 → 키워드 포함 여부 (0~1)
    3. keywords도 없으면 → 전체 모델 후보와 동치 검사 (기준 미상)
    """
    kws: list[str] = criterion.get("keywords", [])
    desc: str = criterion.get("description", "")

    # 키워드에서 수식 후보 추출 (description 제외 — 너무 광범위해 오탐 발생)
    kw_text = " ".join(kws)
    crit_math = _extract_math_expressions(kw_text) if kws else []

    # ── 케이스 1: 키워드에 수식이 있으면 SymPy 동치 검사 ─────────────────────
    if crit_math:
        for sc in student_candidates:
            for mc in crit_math:
                r = verify_math(sc, mc)
                if r.method != "error" and r.is_equivalent:
                    return 1.0
        # 동치 실패 → 키워드 텍스트 포함 여부로 부분 점수
        student_lower = student_full.lower()
        hits = sum(1 for kw in kws if kw.lower() in student_lower)
        return round(hits / len(kws), 4)

    # ── 케이스 2: 키워드가 있지만 수식 미포함 → SymPy 우선, 실패 시 텍스트 매칭 ──
    # 수학 과목에서 키워드가 텍스트 설명만 있어도 SymPy를 먼저 시도한다.
    # (루브릭 생성 시 수식이 빠졌거나, 자동 감지 실패한 경우 대비)
    if kws:
        if student_candidates and model_candidates:
            for sc in student_candidates:
                for mc in model_candidates:
                    r = verify_math(sc, mc)
                    if r.method != "error" and r.is_equivalent:
                        return 1.0
        # SymPy 실패(파싱 불가 또는 비동치) → 키워드 텍스트 매칭 폴백
        student_lower = student_full.lower()
        hits = sum(1 for kw in kws if kw.lower() in student_lower)
        return round(hits / len(kws), 4)

    # ── 케이스 3: 키워드 없음 → 전체 모델 후보와 동치 검사 ──────────────────
    for sc in student_candidates:
        for mc in model_candidates:
            r = verify_math(sc, mc)
            if r.method != "error" and r.is_equivalent:
                return 1.0
    return 0.5  # 판단 불가: 중간값


def _score_keyword_per_criterion(
    student_full: str,
    rubric_items: list[dict],
) -> dict[str, float]:
    """키워드 기반 기준별 점수 (general / 폴백). {criterion_id: 0~1}"""
    student_lower = student_full.lower()
    scores: dict[str, float] = {}
    for item in rubric_items:
        cid = item.get("criterion_id", "")
        kws: list[str] = item.get("keywords", [])
        if not kws:
            scores[cid] = 1.0  # 키워드 없는 기준은 만점
        else:
            hits = sum(1 for kw in kws if kw.lower() in student_lower)
            scores[cid] = round(hits / len(kws), 4)
    return scores


# ── 수학 엔진 ─────────────────────────────────────────────────────────────────
def _math_engine(state: GradingState) -> RuleMetadata:
    """
    SymPy 수식 동치성 검증 단일 결과 → 전체 기준에 균등 적용 (10% 가중치)

    설계 원칙:
      - 수학은 키워드 텍스트 매칭을 완전히 제거. 수식 동치성만으로 Rule-base 평가.
      - 전체 답안 동치 검사 결과(0.0 / 1.0)를 루브릭의 모든 기준에 동일하게 적용.
      - per_criterion_rule_scores = {cid: math_equiv_score_ratio} (모든 기준 동일값)
      - 파싱 실패 시 rule_ratio = 0.0 (평가 불가 → LLM 100% 의존)
    """
    student_full = state["student_answer"].strip()
    model_ans = state["model_answer"].strip()
    rubric = state.get("rubric") or {}
    total = float(rubric.get("total_score", 0))
    rubric_items = rubric.get("rubric_items", [])

    errors: list[dict] = []

    # ── 수식 후보 추출 ────────────────────────────────────────────────────────
    candidates = _extract_math_expressions(student_full)
    if not candidates:
        candidates = [student_full]  # 순수 수식 답안 대비 폴백

    # 모범 답안 수식 후보 추출 (한국어 세그먼트 분리 후 각각 추출)
    _kor_chunks = re.split(r"[가-힣]+", model_ans)
    model_candidates: list[str] = []
    for chunk in _kor_chunks:
        chunk = chunk.strip()
        if chunk:
            for cand in _extract_math_expressions(chunk):
                if cand not in model_candidates:
                    model_candidates.append(cand)
    # 등식 RHS도 별도 후보로 추가 (f(x) = expr → expr 도 시도)
    for mc in list(model_candidates):
        if "=" in mc and not mc.startswith("=="):
            rhs = mc.split("=", 1)[1].strip()
            if rhs and rhs not in model_candidates:
                model_candidates.append(rhs)
    if not model_candidates:
        model_candidates = [model_ans]

    # ── 전체 동치성 검증 ──────────────────────────────────────────────────────
    # 모든 학생↔모델 후보 조합 시도 → 동치 판정 시 즉시 확정
    best_result = None
    best_equiv = False
    parse_attempted = False

    for candidate in candidates:
        for model_cand in model_candidates:
            result = verify_math(candidate, model_cand)
            if result.method != "error":
                parse_attempted = True
                if result.is_equivalent:
                    best_result = result
                    best_equiv = True
                    break
                elif best_result is None:
                    best_result = result
        if best_equiv:
            break

    math_equiv = best_result.to_dict() if best_result else None
    math_equiv_score_ratio = 1.0 if best_equiv else 0.0

    if not parse_attempted:
        errors.append({
            "type": "ParseError",
            "span": student_full[:80],
            "message": "답안에서 수식을 추출할 수 없습니다. Rule-base 점수는 0으로 처리됩니다.",
        })
    elif best_result is not None and not best_equiv:
        errors.append({
            "type": "MathEquivalenceError",
            "span": candidates[0] if candidates else student_full[:80],
            "message": (
                f"수식이 모범 답안과 동치가 아닙니다. "
                f"(방법: {best_result.method}, diff: {best_result.algebraic_diff})"
            ),
        })

    # ── 전체 동치 결과를 모든 기준에 균등 적용 ───────────────────────────────
    # 동치성 검증은 답안 전체에 대한 단일 결과이므로 기준별 구분 없이 동일값 부여.
    # 이 비율이 ensemble_evaluator에서 0.1 × rule_ratio × max_score 로 점수에 반영됨.
    per_criterion_rule_scores: dict[str, float] = {
        item.get("criterion_id", ""): math_equiv_score_ratio
        for item in rubric_items
    }
    rule_base_total = round(sum(per_criterion_rule_scores.values()), 4)
    rule_score = round(total * math_equiv_score_ratio, 2)

    return RuleMetadata(
        subject_tag="math",
        rule_score=rule_score,
        rule_max_score=total,
        errors=errors,
        math_equivalence=math_equiv,
        keyword_hits=[],   # 수학: 키워드 매칭 없음
        keyword_misses=[],
        per_criterion_rule_scores=per_criterion_rule_scores,
        rule_base_total=rule_base_total,
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

    # 기준별 시맨틱 키워드 매칭 (기준당 상위 2개 키워드, 동의어 인정)
    per_criterion_rule_scores, sem_hits, sem_misses = score_keywords_semantic(
        student_text, rubric_items
    )
    rule_base_total = round(sum(per_criterion_rule_scores.values()), 4)

    logger.info(
        "[Node2] 국어 점수: %.2f / %.0f (sem=%.2f, cov=%.2f, disc=%.2f) | "
        "키워드 매칭 rule_base=%.2f (hits=%d, misses=%d)",
        rule_score, total,
        nlp_details["semantic_similarity"],
        nlp_details["criterion_coverage"],
        nlp_details["discourse_structure"],
        rule_base_total, len(sem_hits), len(sem_misses),
    )

    return RuleMetadata(
        subject_tag="korean",
        rule_score=rule_score,
        rule_max_score=total,
        errors=errors,
        math_equivalence=nlp_details,
        keyword_hits=sem_hits,
        keyword_misses=sem_misses,
        per_criterion_rule_scores=per_criterion_rule_scores,
        rule_base_total=rule_base_total,
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

    # 기준별 SBERT 커버리지 → per_criterion_rule_scores (과학도 동일 방식)
    from grading_pipeline.engines.nlp_engine import rubric_criterion_coverage
    rubric_items = (state.get("rubric") or {}).get("rubric_items", [])
    _, per_criterion_list = rubric_criterion_coverage(student_text, rubric_items)
    per_criterion_rule_scores: dict[str, float] = {
        item["criterion_id"]: round(item["coverage"], 4)
        for item in per_criterion_list
    }
    rule_base_total = round(sum(per_criterion_rule_scores.values()), 4)

    logger.info(
        "[Node2] 과학 점수: %.2f / %.0f (sem=%.2f, morph=%.2f, causal=%.2f, kw=%.2f, rule_base=%.2f)",
        rule_score, total,
        nlp_details["semantic_similarity"],
        nlp_details["morpheme_overlap"],
        nlp_details["causal_structure_score"],
        nlp_details["keyword_hit_ratio"],
        rule_base_total,
    )

    return RuleMetadata(
        subject_tag="science",
        rule_score=rule_score,
        rule_max_score=total,
        errors=errors,
        math_equivalence=nlp_details,
        keyword_hits=keyword_hits,
        keyword_misses=keyword_misses,
        per_criterion_rule_scores=per_criterion_rule_scores,
        rule_base_total=rule_base_total,
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
    """일반 과목: 시맨틱 키워드 매칭 (기준당 상위 2개 키워드, 동의어 인정)"""
    rubric = state.get("rubric") or {}
    total = float(rubric.get("total_score", 0))
    rubric_items = rubric.get("rubric_items", [])
    student_text = state["student_answer"]

    # 시맨틱 키워드 매칭으로 per-criterion 점수 산출
    per_criterion_rule_scores, sem_hits, sem_misses = score_keywords_semantic(
        student_text, rubric_items
    )
    rule_base_total = round(sum(per_criterion_rule_scores.values()), 4)

    # 요약 점수 (레거시 호환: 기준별 평균)
    hit_ratio = rule_base_total / len(rubric_items) if rubric_items else 0.0
    rule_score = round(total * hit_ratio, 2)

    errors = [
        {"type": "KeywordMissing", "span": "", "message": f"핵심어 미매칭: {kw}"}
        for kw in sem_misses
    ]

    return RuleMetadata(
        subject_tag=subject_tag,
        rule_score=rule_score,
        rule_max_score=total,
        errors=errors,
        math_equivalence=None,
        keyword_hits=sem_hits,
        keyword_misses=sem_misses,
        per_criterion_rule_scores=per_criterion_rule_scores,
        rule_base_total=rule_base_total,
    )
