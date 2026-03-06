"""
한국어 NLP 공통 엔진

구성 요소:
  - Kiwipiepy : 형태소 분석 (명사·동사·형용사 추출) — 순수 Python, Java 불필요
  - sentence-transformers : 의미적 유사도 + 루브릭 기준 커버리지
      모델: jhgan/ko-sroberta-multitask (한국어 특화 Sentence-BERT)

두 모듈 모두 첫 호출 시에만 로드(lazy loading)하여 서버 시작 속도에 영향 없음.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

# ── 모델 상수 ──────────────────────────────────────────────────────────────────
# 한국어 Sentence-BERT: NLI + STS 멀티태스크 학습, 의미 유사도에 최적화
_SBERT_MODEL = "jhgan/ko-sroberta-multitask"

# Kiwipiepy 추출 대상 품사 (의미 있는 내용어만)
# NNG: 일반명사, NNP: 고유명사, VV: 동사, VA: 형용사, XR: 어근
_CONTENT_POS = {"NNG", "NNP", "VV", "VA", "XR", "SL"}  # SL: 외래어


# ── Lazy 로더 ─────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_kiwi():
    """Kiwi 형태소 분석기 — 최초 호출 시 초기화"""
    from kiwipiepy import Kiwi
    kiwi = Kiwi()
    logger.info("[NLP] Kiwipiepy 초기화 완료")
    return kiwi


@lru_cache(maxsize=1)
def _get_sbert():
    """Sentence-BERT 모델 — 최초 호출 시 다운로드/로드"""
    from sentence_transformers import SentenceTransformer
    logger.info("[NLP] Sentence-BERT 모델 로드 중: %s", _SBERT_MODEL)
    model = SentenceTransformer(_SBERT_MODEL)
    logger.info("[NLP] Sentence-BERT 로드 완료")
    return model


# ── 형태소 분석 ───────────────────────────────────────────────────────────────

def extract_content_words(text: str) -> list[str]:
    """
    텍스트에서 내용어(명사·동사·형용사·어근·외래어) 추출.
    원형(lemma)으로 변환하여 반환.

    예: "광합성을 통해 포도당을 생성한다" → ["광합성", "포도당", "생성하다"]
    """
    try:
        kiwi = _get_kiwi()
        result = kiwi.analyze(text)
        # result: [(token_list, score), ...] — 최고 확률 분석 결과 사용
        token_list = result[0][0]
        tokens = [
            token.form
            for token in token_list
            if token.tag in _CONTENT_POS
        ]
        return tokens
    except Exception as e:
        logger.warning("[NLP] 형태소 분석 실패: %s", e)
        return text.split()


# ── 의미적 유사도 ─────────────────────────────────────────────────────────────

def semantic_similarity(text_a: str, text_b: str) -> float:
    """
    두 텍스트 간 코사인 유사도 계산 (0.0 ~ 1.0).
    sentence-transformers로 임베딩 후 코사인 유사도.
    """
    try:
        model = _get_sbert()
        embeddings = model.encode([text_a, text_b], convert_to_numpy=True)
        sim = float(cosine_similarity([embeddings[0]], [embeddings[1]])[0][0])
        # 음수 클리핑 (코사인 유사도가 간혹 음수 나올 수 있음)
        return max(0.0, min(1.0, sim))
    except Exception as e:
        logger.warning("[NLP] 의미 유사도 계산 실패: %s", e)
        return 0.0


# ── 형태소 기반 내용어 겹침률 ─────────────────────────────────────────────────

def morpheme_overlap_ratio(student_text: str, model_text: str) -> float:
    """
    학생 답안과 모범 답안 간 내용어 겹침률 (Jaccard 유사도).
    의미 유사도를 보완하는 정확한 어휘 일치 지표.
    과학 문항의 전문 용어 측정에 활용.

    반환: 0.0 ~ 1.0
    """
    student_tokens = set(extract_content_words(student_text))
    model_tokens = set(extract_content_words(model_text))

    if not model_tokens:
        return 1.0  # 모범 답안 내용어 없으면 만점 처리

    intersection = student_tokens & model_tokens
    # Recall 기준: 모범 답안 핵심어 중 학생이 언급한 비율
    return len(intersection) / len(model_tokens)


# ── 시맨틱 키워드 매칭 (국어/일반 전용) ──────────────────────────────────────

# 동의어 판단 기준 코사인 유사도 임계값 (구 수준 비교 기준)
_KEYWORD_SIM_THRESHOLD = 0.60


def select_top_keywords(keywords: list[str], n: int = 2) -> list[str]:
    """
    키워드 목록에서 상위 n개를 선택한다.
    루브릭 생성기가 중요도 순으로 키워드를 배열한다고 가정하고 앞에서 n개 반환.
    n보다 적으면 전체 반환.
    """
    return keywords[:n] if len(keywords) > n else list(keywords)


def _build_comparison_phrases(content_words: list[str]) -> list[str]:
    """
    내용어 목록에서 SBERT 비교 대상 구(phrase)를 생성한다.

    단일 2글자 한국어 단어는 SBERT 임베딩 공간에서 모두 ~0.9955로 수렴하여
    의미 구분이 불가능하다. 이를 피하기 위해:
      - 3글자 이상 단어: 단독 사용
      - 연속 2단어 바이그램: "권력 독점" 처럼 조합
      - 연속 3단어 트라이그램: 더 많은 문맥
    이렇게 구 수준으로 비교하면 2글자 단어의 임베딩 붕괴 문제를 우회할 수 있다.
    """
    phrases: list[str] = []
    # 3자 이상 단독어
    phrases.extend(w for w in content_words if len(w) >= 3)
    # 연속 2단어 바이그램
    phrases.extend(
        content_words[i] + " " + content_words[i + 1]
        for i in range(len(content_words) - 1)
    )
    # 연속 3단어 트라이그램
    phrases.extend(
        content_words[i] + " " + content_words[i + 1] + " " + content_words[i + 2]
        for i in range(len(content_words) - 2)
    )
    return phrases if phrases else [" ".join(content_words)] if content_words else []


def semantic_keyword_match(
    keyword: str,
    student_text: str,
    threshold: float = _KEYWORD_SIM_THRESHOLD,
) -> tuple[bool, float]:
    """
    키워드가 학생 답안에 의미적으로 포함되어 있는지 판단.

    3단계 전략:
      1. 정확 텍스트 포함 여부 (빠른 경로)
      2. 형태소 공유 매칭: 2자 이상 공통 부분 공유 시 동의 변형으로 인정
         예: "광합성" ↔ "합성하다" → "합성" 공유 → 매칭
      3. SBERT 구(phrase) 수준 비교:
         - 2글자 단어 단독 비교 시 SBERT 임베딩이 ~0.9955로 수렴하는 문제 회피
         - 3자 이상 단어 + 바이그램/트라이그램 조합과 비교
         - 임계값 0.60 (단어↔단어 0.72보다 낮음, 구 수준 범위에 최적화)

    반환: (is_match: bool, max_similarity: float)
    """
    student_lower = student_text.lower()

    # 1단계: 정확 포함 (빠른 경로)
    if keyword.lower() in student_lower:
        return True, 1.0

    try:
        content_words = extract_content_words(student_text)

        # 2단계: 형태소 공유 매칭
        kw_lower = keyword.lower()
        for word in content_words:
            w = word.lower()
            # 어느 한 쪽이 다른 쪽을 포함하면 동의 변형으로 인정 (최소 2자)
            if (kw_lower in w or w in kw_lower) and min(len(kw_lower), len(w)) >= 2:
                return True, 0.92
            # 4자 이상 키워드: 앞 2자 공유 시 인정 (예: "세포분열" ↔ "세포막")
            if len(kw_lower) >= 4 and len(w) >= 2:
                for n in range(2, min(len(kw_lower), len(w)) + 1):
                    if kw_lower[:n] == w[:n]:
                        return True, 0.88

        # 3단계: SBERT 구(phrase) 수준 비교
        phrases = _build_comparison_phrases(content_words)
        if not phrases:
            phrases = [student_text]

        model = _get_sbert()
        kw_emb = model.encode([keyword], convert_to_numpy=True)[0]
        phrase_embs = model.encode(phrases, convert_to_numpy=True)
        sims = cosine_similarity([kw_emb], phrase_embs)[0]
        phrase_max = float(max(sims))

        return phrase_max >= threshold, round(phrase_max, 4)

    except Exception as e:
        logger.warning("[NLP] 시맨틱 키워드 매칭 실패 (%s): %s", keyword, e)
        return False, 0.0


def score_keywords_semantic(
    student_text: str,
    rubric_items: list[dict],
    threshold: float = _KEYWORD_SIM_THRESHOLD,
) -> tuple[dict[str, float], list[str], list[str]]:
    """
    국어/일반 과목: 기준별 시맨틱 키워드 점수 산출.

    - 기준당 최대 2개 키워드만 선택
    - 각 키워드에 대해 semantic_keyword_match 수행
    - 동의어/유사어 포함 시 매칭 인정

    반환:
      per_criterion_scores : {criterion_id: float(0~1)}
      semantic_hits        : 매칭된 키워드 목록 (표시용)
      semantic_misses      : 미매칭 키워드 목록 (표시용)
    """
    per_criterion_scores: dict[str, float] = {}
    semantic_hits: list[str] = []
    semantic_misses: list[str] = []

    for item in rubric_items:
        cid = item.get("criterion_id", "")
        all_kws: list[str] = item.get("keywords", [])
        top_kws = select_top_keywords(all_kws, n=2)

        if not top_kws:
            per_criterion_scores[cid] = 1.0  # 키워드 없는 기준은 만점
            continue

        matched = 0
        for kw in top_kws:
            is_match, sim = semantic_keyword_match(kw, student_text, threshold)
            if is_match:
                matched += 1
                semantic_hits.append(f"{kw}(유사도:{sim:.2f})")
            else:
                semantic_misses.append(f"{kw}(유사도:{sim:.2f})")

        per_criterion_scores[cid] = round(matched / len(top_kws), 4)

    return per_criterion_scores, semantic_hits, semantic_misses


# ── 문장 분리 ─────────────────────────────────────────────────────────────────

def _split_into_chunks(text: str) -> list[str]:
    """
    텍스트를 문장 단위로 분리. 5자 미만 토막은 제외.
    루브릭 기준 커버리지 계산 시 슬라이딩 윈도 역할.
    """
    sentences = re.split(r"[.!?\n]+", text)
    chunks = [s.strip() for s in sentences if len(s.strip()) >= 5]
    return chunks if chunks else [text]


# ── 루브릭 기준 커버리지 (국어 논술 전용) ─────────────────────────────────────

def rubric_criterion_coverage(
    student_text: str,
    rubric_items: list[dict],
) -> tuple[float, list[dict]]:
    """
    각 루브릭 평가 기준 항목에 대해 학생 답안의 의미적 커버리지를 측정.

    방법:
      기준 description + keywords 텍스트를 SBERT 임베딩.
      학생 답안을 문장 단위로 분리한 뒤 각 문장과 코사인 유사도 계산.
      최대값을 해당 기준의 커버리지 점수로 사용.
      → 학생이 어느 문장에서든 해당 평가 포인트를 다루면 인정.

    키워드 정확 매칭과의 차이:
      "광합성으로 에너지를 만들어낸다"는 키워드 "광합성을 통한 에너지 생산"과
      정확 매칭에서는 0점이지만, SBERT 커버리지에서는 높은 점수 부여.

    반환: (가중평균 커버리지 0~1, 기준별 상세 리스트)
    """
    if not rubric_items:
        return 0.0, []

    try:
        model = _get_sbert()
        chunks = _split_into_chunks(student_text)
        if not chunks:
            return 0.0, []

        # 학생 답안 문장 임베딩 (배치 처리)
        chunk_embeddings = model.encode(chunks, convert_to_numpy=True)

        total_weight = sum(float(item.get("max_score", 1)) for item in rubric_items)
        weighted_sum = 0.0
        per_criterion: list[dict] = []

        for item in rubric_items:
            # 기준 텍스트: description + keywords 결합
            criterion_text = item.get("description", "")
            keywords = item.get("keywords", [])
            if keywords:
                criterion_text += " " + " ".join(keywords)

            criterion_emb = model.encode([criterion_text], convert_to_numpy=True)[0]
            sims = cosine_similarity([criterion_emb], chunk_embeddings)[0]
            coverage = float(max(sims)) if len(sims) > 0 else 0.0
            coverage = max(0.0, min(1.0, coverage))

            weight = float(item.get("max_score", 1))
            weighted_sum += weight * coverage

            per_criterion.append({
                "criterion_id": item.get("criterion_id", ""),
                "description": item.get("description", ""),
                "coverage": round(coverage, 4),
                "max_score": weight,
            })

        overall = weighted_sum / total_weight if total_weight > 0 else 0.0
        return round(overall, 4), per_criterion

    except Exception as e:
        logger.warning("[NLP] 루브릭 기준 커버리지 계산 실패: %s", e)
        return 0.0, []


# ── 인과·논리 구조 점수 (과학 전용) ──────────────────────────────────────────

# 과학 인과 관계 표현 패턴
_CAUSAL_PATTERNS = re.compile(
    r"때문[에]?|로\s*인[해하]|결과(?:적으로)?|따라서|이므로|"
    r"원인|영향|반응하[면여]|생성[된다됨]|분해[된다됨]|"
    r"증가|감소|활성화|억제|촉진"
)


def causal_structure_score(text: str) -> float:
    """
    텍스트에서 인과·논리 구조 표현이 얼마나 사용됐는지 점수화.
    과학 문항에서 현상의 원인·결과 설명 능력 평가.

    반환: 0.0 ~ 1.0 (최대 3개 표현 기준 정규화)
    """
    matches = _CAUSAL_PATTERNS.findall(text)
    unique_matches = set(matches)
    score = min(len(unique_matches) / 3.0, 1.0)  # 3개 이상이면 만점
    return score


# ── 논리적 구조 표현 점수 (국어 논술 전용) ────────────────────────────────────

# 논술 담화 구조 마커: 주장-근거-반론-결론-전개
_DISCOURSE_MARKERS: dict[str, re.Pattern] = {
    # 주장 표현: "~라고 생각한다", "주장한다", "봐야 한다"
    "claim": re.compile(
        r"주장(?:하면)?|의견(?:으로)?|(?:생각|판단)(?:한다|하기에|하면|됩니다|해야)|봐야|것이다|것으로\s*본다"
    ),
    # 근거 제시: "왜냐하면", "예를 들어", "근거로"
    "evidence": re.compile(
        r"왜냐하면|예를\s*들(?:어|면)|근거(?:로|하여|가)?|이유(?:는|로|가)?|때문에|사례(?:로|를)?|실제로|따르면"
    ),
    # 반론 인정: "물론 ~이지만", "비록", "그러나"
    "concession": re.compile(
        r"물론|비록|이지만|반면(?:에)?|그럼에도|하지만|그러나|그런데|반론"
    ),
    # 결론 도출: "따라서", "결론적으로", "정리하면"
    "conclusion": re.compile(
        r"따라서|결론(?:적으로|은|을)?|종합하면|요약하면|이로써|정리하면|결국|그러므로"
    ),
    # 내용 전개: "또한", "게다가", "뿐만 아니라"
    "elaboration": re.compile(
        r"또한|게다가|뿐만\s*아니라|더불어|나아가|특히|아울러"
    ),
}


def discourse_structure_score(text: str) -> tuple[float, dict]:
    """
    논술 글쓰기의 논리적 구조 표현 점수화.
    주장(Claim) → 근거(Evidence) → 결론(Conclusion) 구조 여부,
    접속어·전개어 활용도를 평가.

    가중치:
      - 근거 제시 (evidence)    : 40%
      - 주장 표현 (claim)       : 25%
      - 결론 도출 (conclusion)  : 20%
      - 내용 전개 (elaboration) : 10%
      - 반론 인정 (concession)  :  5%

    각 카테고리는 해당 마커 2종류 이상 사용 시 만점(1.0).

    반환: (종합 점수 0~1, 카테고리별 점수 dict)
    """
    detail: dict[str, float] = {}
    for name, pattern in _DISCOURSE_MARKERS.items():
        matches = pattern.findall(text)
        # 2종류 이상 표현이면 해당 카테고리 만점
        detail[name] = min(len(set(matches)) / 2.0, 1.0)

    score = (
        0.40 * detail["evidence"]
        + 0.25 * detail["claim"]
        + 0.20 * detail["conclusion"]
        + 0.10 * detail["elaboration"]
        + 0.05 * detail["concession"]
    )
    return round(score, 4), {k: round(v, 4) for k, v in detail.items()}


# ── 복합 점수 산출 ─────────────────────────────────────────────────────────────

def score_korean(
    student_text: str,
    model_text: str,
    rubric_items: list[dict],
) -> tuple[float, dict]:
    """
    국어 논술 문항 종합 점수 (0.0 ~ 1.0)

    가중치:
      - 의미적 유사도 (SBERT, 모범답안 기준)  : 30%
      - 루브릭 기준 커버리지 (SBERT, 기준별)  : 50%
      - 논리적 구조 표현 점수                : 20%

    키워드 정확 매칭·형태소 겹침률 제거:
      → 논술에서 같은 개념을 다양한 표현으로 기술하므로
        의미 기반 커버리지로 대체.

    Returns:
      (score_ratio, details_dict)
    """
    sem_sim = semantic_similarity(student_text, model_text)
    criterion_coverage, per_criterion = rubric_criterion_coverage(student_text, rubric_items)
    discourse_score, discourse_detail = discourse_structure_score(student_text)

    score_ratio = (
        0.30 * sem_sim
        + 0.50 * criterion_coverage
        + 0.20 * discourse_score
    )

    details = {
        "semantic_similarity": round(sem_sim, 4),
        "criterion_coverage": round(criterion_coverage, 4),
        "discourse_structure": round(discourse_score, 4),
        "discourse_detail": discourse_detail,
        "per_criterion_coverage": per_criterion,
        "model": _SBERT_MODEL,
    }
    return round(score_ratio, 4), details


def score_science(
    student_text: str,
    model_text: str,
    keyword_hit_ratio: float,
) -> tuple[float, dict]:
    """
    과학 문항 종합 점수 (0.0 ~ 1.0)

    과학은 논술과 달리 전문 용어 정확 사용이 중요하므로
    형태소 겹침률(전문 용어 recall) 유지.

    가중치:
      - 의미적 유사도 (SBERT)   : 40%
      - 형태소 내용어 겹침률    : 20%
      - 루브릭 키워드 적중률    : 25%
      - 인과·논리 구조 점수     : 15%

    Returns:
      (score_ratio, details_dict)
    """
    sem_sim = semantic_similarity(student_text, model_text)
    morph_overlap = morpheme_overlap_ratio(student_text, model_text)
    causal_score = causal_structure_score(student_text)

    score_ratio = (
        0.40 * sem_sim
        + 0.20 * morph_overlap
        + 0.25 * keyword_hit_ratio
        + 0.15 * causal_score
    )

    details = {
        "semantic_similarity": round(sem_sim, 4),
        "morpheme_overlap": round(morph_overlap, 4),
        "keyword_hit_ratio": round(keyword_hit_ratio, 4),
        "causal_structure_score": round(causal_score, 4),
        "model": _SBERT_MODEL,
    }
    return round(score_ratio, 4), details
