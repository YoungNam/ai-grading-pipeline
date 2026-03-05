# Handoff — AI 자동 채점 파이프라인

**최종 업데이트**: 2026-03-06
**작업 디렉터리**: `/Users/justin0/ai_Projects/`
**프로젝트 명세 원본**: `claude.md/1. 프로젝트 개요 (Overview).md`

---

## 1. 프로젝트 목적

규칙 기반(Rule-base) 엔진과 다중 LLM 앙상블(Multi-LLM Ensemble)을 결합하여
한국어 **서논술형 문항 / 수식 / 과학 논술**을 자동 채점하고 피드백을 생성하는 시스템.

- **백엔드**: LangGraph 파이프라인 + FastAPI SSE 서버
- **프론트엔드**: Next.js 16 교사 대시보드 (루브릭 생성 + 채점 + HITL 검수)

---

## 2. 전체 파일 구조

```
ai_Projects/
├── claude.md/
│   └── 1. 프로젝트 개요 (Overview).md     ← 원본 명세 (업데이트 완료)
├── handoff.md                              ← 이 파일
│
├── api/                                    ← FastAPI 서버 (신규)
│   ├── server.py
│   └── requirements.txt
│
├── grading_pipeline/                       ← LangGraph 파이프라인
│   ├── __init__.py
│   ├── state.py
│   ├── prompts.py
│   ├── graph.py
│   ├── requirements.txt
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── math_verifier.py               ← SymPy 수식 동치성 검증
│   │   └── nlp_engine.py                  ← 한국어 NLP (SBERT + Kiwipiepy)
│   └── nodes/
│       ├── __init__.py
│       ├── rubric_generator.py            ← Node 1
│       ├── rule_based_router.py           ← Node 2
│       ├── ensemble_evaluator.py          ← Node 3
│       └── hitl_node.py                   ← Node 4
│
└── frontend/                              ← Next.js 16 앱 (신규)
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx                       ← /setup 리다이렉트
    │   ├── setup/page.tsx                 ← 루브릭 생성 화면
    │   └── grading/page.tsx               ← 채점 + HITL 화면
    ├── components/
    │   ├── layout/sidebar.tsx
    │   ├── rubric/
    │   │   ├── evaluation-form.tsx
    │   │   └── rubric-table.tsx
    │   └── grading/
    │       ├── student-form.tsx
    │       ├── grading-progress.tsx
    │       └── hitl-panel.tsx
    ├── hooks/useAgentStream.ts
    ├── lib/api.ts
    └── .env.local                         ← NEXT_PUBLIC_API_URL (gitignore)
```

---

## 3. 노드별 구현 상태

| 노드 | 파일 | 상태 | 비고 |
|------|------|------|------|
| Node 1: Rubric Generator | `nodes/rubric_generator.py` | **완료** | Claude Opus 4.6 |
| Node 2: Rule-based Router | `nodes/rule_based_router.py` | **완료** | 과목별 엔진 모두 구현 |
| Node 3: Ensemble Evaluator | `nodes/ensemble_evaluator.py` | **완료** | GPT·Gemini 선택적 로드 |
| Node 4: HITL | `nodes/hitl_node.py` | **구조 완료** | FastAPI 세션 방식으로 대체 |
| SymPy 검증 모듈 | `engines/math_verifier.py` | **완료** | |
| NLP 엔진 | `engines/nlp_engine.py` | **완료** | SBERT + Kiwipiepy |
| FastAPI 서버 | `api/server.py` | **완료** | SSE 스트리밍 |
| Next.js 프론트엔드 | `frontend/` | **완료** | 교사 대시보드 |

---

## 4. 아키텍처 흐름

```
START
  │
  ▼
[Node 1] rubric_generator
  │  Claude Opus 4.6 → Bloom's Taxonomy 기반 JSON 루브릭 자동 생성
  │
  ▼
[Node 2] rule_based_router
  │  subject_tag 결정 → 결정론적 엔진 실행
  │  math    → SymPy 수식 동치성 검증 (60%) + 키워드 적중률 (40%)
  │  korean  → SBERT 의미 유사도 (30%) + 루브릭 기준 커버리지 (50%) + 논리 구조 (20%)
  │  science → SBERT 의미 유사도 (40%) + 형태소 겹침률 (20%) + 키워드 (25%) + 인과 구조 (15%)
  │  general → 키워드 매칭 (100%)
  │
  ▼
[Node 3] ensemble_evaluator
  │  ThreadPoolExecutor → 3개 LLM 병렬 평가
  │  stdev > 1.5 → Debate 체인 가동 (Claude Opus 조율)
  │  Aggregator → 가중 평균 점수 + 종합 피드백
  │
  ▼
[FastAPI SSE] hitl_ready 이벤트 전송
  │  교사 브라우저에서 HITL 검수 패널 표시
  │  교사 승인/수정 → POST /api/hitl-decision
  │
  ▼
END (최종 점수 + 피드백 반환)
```

---

## 5. 핵심 설계 결정 사항

### 5-1. HITL 구현 방식 (LangGraph interrupt → FastAPI 세션)

LangGraph `interrupt()`는 그래프 실행을 일시 중단하고 외부 입력을 기다리는 방식이나,
SSE 스트리밍 중 노드 직접 호출 구조에서는 세션 딕셔너리로 대체:

```python
# api/server.py
SESSIONS: dict[str, GradingState] = {}  # thread_id → 채점 상태

# 채점 완료 후
SESSIONS[thread_id] = state
yield _sse("hitl_ready", {...})          # 프론트엔드 대기

# 교사 결정 수신 (별도 POST 엔드포인트)
@app.post("/api/hitl-decision")
def hitl_decision(req):
    state = SESSIONS.pop(req.thread_id)
    final_score = req.corrected_score or state["ensemble_score"]
    ...
```

### 5-2. subject_tag 라우팅 파이프라인

```
Setup 화면 → 과목 선택 (FormMeta) → sessionStorage 저장
Grading 화면 → sessionStorage에서 subject/model_answer 읽음
FastAPI → initial_state(subject_tag=subject) 전달
Node 2 → _resolve_subject_tag() → 명시 태그 우선, auto면 키워드/수식 패턴 감지
```

### 5-3. 국어 논술 평가 지표 (v2 — 키워드 정확 매칭 폐기)

| 지표 | 가중치 | 방법 |
|------|--------|------|
| 모범답안 의미 유사도 | 30% | SBERT 코사인 유사도 |
| 루브릭 기준 커버리지 | 50% | 각 기준 description+keywords 임베딩 → 학생 답안 문장 분할 → 최대 유사도 가중 평균 |
| 논리 구조 표현 | 20% | 주장·근거·결론·전개·반론 마커 패턴 감지 |

**폐기 이유**: 키워드 정확 매칭은 논술에서 구조적으로 항상 0에 가까움.
형태소 겹침률도 표현 방식이 달리면 무의미. SBERT 기반 의미 커버리지로 대체.

### 5-4. LLM 모델 배정

| 역할 | 모델 |
|------|------|
| 루브릭 생성 | `claude-opus-4-6` |
| 개별 평가 | `claude-sonnet-4-6` + `gpt-4o-mini`(선택) + `gemini-2.0-flash`(선택) |
| Aggregator / Debate | `claude-opus-4-6` |

### 5-5. SymPy 수식 검증 3단계 전략

```
1순위: simplify(student - model) == 0   (대수적 완전 동치)
2순위: evalf() 10회 무작위 수치 대입    (90% 이상 통과 시 동치)
방정식: solve() 해집합 비교             (= 기호 감지 시 자동 분기)
전처리: 자연어 답안에서 수식 후보 추출 (_extract_math_expressions)
가중치: 수식 동치성 60% + 키워드 40% (파싱 실패 시 키워드 100%)
```

---

## 6. FastAPI 서버 엔드포인트

| 메서드 | 경로 | 역할 |
|--------|------|------|
| GET | `/health` | 서버 상태 + API 키 확인 |
| POST | `/api/generate-rubric` | Node 1만 실행, JSON 루브릭 반환 |
| GET | `/api/grade-stream` | Node 1-3 SSE 스트리밍 + HITL 대기 |
| POST | `/api/hitl-decision` | 교사 승인/수정 → final_score 반환 |

### SSE 이벤트 타입

| type | 내용 |
|------|------|
| `started` | thread_id 발급 |
| `progress` | 단계 메시지 + step + progress(0-100) |
| `rubric_done` | 생성된 루브릭 JSON |
| `rule_done` | Rule-base 분석 결과 (rule_metadata) |
| `hitl_ready` | 앙상블 결과 + evaluator_results + rule_metadata |
| `error` | 오류 메시지 |

---

## 7. 프론트엔드 화면 구조

### 화면 1: `/setup` — 루브릭 생성
- 과목(select) + 총점(number) + 문항(textarea) + 모범답안(textarea)
- `POST /api/generate-rubric` → RubricTable (인라인 편집 가능)
- "채점 시작" → sessionStorage에 rubric + FormMeta 저장 후 `/grading` 이동

### 화면 2: `/grading` — 채점 + HITL 검수
- 학생 답안 입력 → `GET /api/grade-stream` EventSource 연결
- GradingProgress: 4단계 진행 바 (SSE 이벤트 수신 시 업데이트)
- HitlPanel (hitl_ready 수신 후 표시):
  - **섹션 1** Rule-base 분석 지표:
    - 규칙 기반 점수 바
    - 수학: SymPy 동치성 카드 (동치여부/방법/수치통과율)
    - 국어: NLP 카드 (모범답안 유사도/루브릭 커버리지/논리 구조)
    - 국어 펼치기: 기준별 커버리지 미니 바 + 논리 구조 카테고리별 ✓△✗
    - 과학: NLP 카드 (유사도/형태소 겹침/인과 구조)
  - **섹션 2** AI 앙상블 채점: 모델별 총점 카드 + 기준×모델 점수 테이블
  - **섹션 3** 교사 검수: 점수 조정 + 피드백 편집 + 승인/수정 제출

---

## 8. 실행 방법

### 백엔드
```bash
cd /Users/justin0/ai_Projects
# 의존성 설치 (최초 1회)
pip install -r api/requirements.txt
pip install -r grading_pipeline/requirements.txt
pip install sentence-transformers kiwipiepy scikit-learn

# 환경변수 설정
export ANTHROPIC_API_KEY=sk-ant-...   # 필수
export OPENAI_API_KEY=sk-...          # 선택
export GOOGLE_API_KEY=AI...           # 선택

# 서버 실행
python3 -m uvicorn api.server:app --reload --port 8000
```

### 프론트엔드
```bash
cd /Users/justin0/ai_Projects/frontend
npm run dev   # localhost:3000
```

---

## 9. 환경변수

### 백엔드 (`api/.env` 또는 시스템 환경변수)
```
ANTHROPIC_API_KEY=        # 필수
OPENAI_API_KEY=           # 선택 (GPT 평가 비활성화 가능)
GOOGLE_API_KEY=           # 선택 (Gemini 평가 비활성화 가능)
NEO4J_URI=                # 선택 (미설정 시 저장 스킵)
NEO4J_USER=neo4j
NEO4J_PASSWORD=
```

### 프론트엔드 (`frontend/.env.local`)
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 10. 조정 가능한 주요 상수

| 위치 | 상수 | 기본값 | 설명 |
|------|------|--------|------|
| `ensemble_evaluator.py` | `_DEBATE_THRESHOLD` | `1.5` | 토론 가동 표준편차 임계값 |
| `math_verifier.py` | `_NUMERIC_SAMPLES` | `10` | 수치 검증 샘플 수 |
| `math_verifier.py` | `_NUMERIC_TOLERANCE` | `1e-9` | 수치 허용 절대 오차 |
| `nlp_engine.py` | `_SBERT_MODEL` | `jhgan/ko-sroberta-multitask` | 한국어 Sentence-BERT 모델 |
| `nlp_engine.py` | `score_korean()` | sem:30%, cov:50%, disc:20% | 국어 평가 가중치 |
| `nlp_engine.py` | `score_science()` | sem:40%, morph:20%, kw:25%, causal:15% | 과학 평가 가중치 |

---

## 11. 알려진 제약 / 미완성 항목

| 항목 | 상태 | 비고 |
|------|------|------|
| Neo4j 저장 | 미연결 (스킵) | 드라이버 미설치 시 자동 비활성화 |
| Llama-3 70B | 미연결 | Groq/Together.ai/Ollama 중 선택 필요 |
| GPT 모델 | `gpt-4o-mini` 임시 | GPT-5 mini 출시 후 업데이트 |
| SESSIONS 인메모리 | 서버 재시작 시 소멸 | 프로덕션 전환 시 Redis 등으로 교체 필요 |
| LangGraph graph.invoke | 미사용 | 노드 직접 호출 방식으로 SSE 구현 |

---

## 12. 버그 수정 이력

| 날짜 | 버그 | 수정 |
|------|------|------|
| 2026-03-06 | SymPy `ImplicitMultiplicationApplication` 제거됨 | `implicit_multiplication_application` 함수로 교체 |
| 2026-03-06 | Rule-base 수학 점수 항상 0 | 자연어 텍스트 전체를 SymPy에 넘기던 버그 → `_extract_math_expressions()` 추가 |
| 2026-03-06 | Kiwipiepy API `result[0].tokens` 오류 | `result[0][0]` 으로 수정 |
| 2026-03-06 | 국어 문항이 수식 동치성으로 평가됨 | `subject_tag` 전달 경로 수정 (FormMeta → sessionStorage → GradingParams) |
| 2026-03-06 | 국어 키워드 적중률 항상 0 | 평가 지표 구조 개편 (키워드 정확 매칭 → SBERT 기준 커버리지) |
| 2026-03-06 | ensemble_evaluator max_tokens=1024 JSON 절단 | 4096으로 증가 |
