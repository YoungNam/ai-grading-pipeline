# AI 자동 채점 파이프라인

한국어 서논술형 문항·수식·과학 논술을 자동 채점하는 Rule-base + Multi-LLM Ensemble 시스템.
교사 HITL(Human-in-the-Loop) 검수 웹 대시보드 포함.

## 구성

```
api/               FastAPI SSE 서버
grading_pipeline/  LangGraph 파이프라인 (Node 1~4 + 엔진)
frontend/          Next.js 16 교사 대시보드
```

## 빠른 시작

### 백엔드
```bash
pip install -r api/requirements.txt
pip install -r grading_pipeline/requirements.txt
pip install sentence-transformers kiwipiepy scikit-learn

export ANTHROPIC_API_KEY=sk-ant-...
python3 -m uvicorn api.server:app --reload --port 8000
```

### 프론트엔드
```bash
cd frontend
npm install
npm run dev   # localhost:3000
```

자세한 내용은 `handoff.md` 참고.
