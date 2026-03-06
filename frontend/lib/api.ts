/**
 * API 클라이언트 — FastAPI 서버 통신 유틸리티
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── 타입 정의 ─────────────────────────────────────────────────────────────────

export interface RubricItem {
  criterion_id: string;
  description: string;
  max_score: number;
  bloom_level: string;
  keywords: string[];
}

export interface Rubric {
  task_description: string;
  cognitive_level: string;
  total_score: number;
  rubric_items: RubricItem[];
}

export interface RuleMetadata {
  subject_tag: string;
  rule_score: number;
  rule_max_score: number;
  errors: Array<{ type: string; span: string; message: string }>;
  math_equivalence: Record<string, unknown> | null;
  keyword_hits: string[];
  keyword_misses: string[];
  per_criterion_rule_scores: Record<string, number>;
  rule_base_total: number;
}

export interface EvaluatorResult {
  model_name: string;
  criterion_scores: Array<{
    criterion_id: string;
    score: number;
    rationale: string;
    original_llm_score?: number;
    rule_ratio?: number;
  }>;
  total_score: number;
  original_llm_total?: number;
  feedback: string;
}

export interface HitlDecisionRequest {
  thread_id: string;
  approved: boolean;
  corrected_score?: number;
  corrected_feedback?: string;
  correction_note?: string;
}

export interface HitlDecisionResponse {
  thread_id: string;
  teacher_approved: boolean;
  final_score: number;
  final_feedback: string;
}

// ── SSE 이벤트 타입 ──────────────────────────────────────────────────────────

export type SSEEventData =
  | { type: "started"; thread_id: string }
  | { type: "progress"; message: string; step: number; progress: number }
  | { type: "rubric_done"; rubric: Rubric }
  | { type: "rule_done"; rule_metadata: RuleMetadata | null }
  | {
      type: "hitl_ready";
      thread_id: string;
      ensemble_score: number;
      ensemble_feedback: string;
      grand_total: number | null;
      rule_base_total: number;
      per_criterion_rule_scores: Record<string, number>;
      total_score: number;
      evaluator_results: Array<{
        model_name: string;
        total_score: number;
        original_llm_total?: number;
        feedback: string;
        criterion_scores: Array<{
          criterion_id: string;
          score: number;
          rationale: string;
          original_llm_score?: number;
          rule_ratio?: number;
        }>;
      }>;
      debate_log: string[];
      rule_metadata: RuleMetadata | null;
    }
  | { type: "error"; message: string };

// ── API 함수 ─────────────────────────────────────────────────────────────────

/**
 * 루브릭 생성 API 호출
 */
export async function generateRubric(params: {
  subject: string;
  question: string;
  model_answer: string;
  total_score: number;
}): Promise<{ rubric: Rubric }> {
  const res = await fetch(`${API_URL}/api/generate-rubric`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "루브릭 생성 실패");
  }
  return res.json();
}

/**
 * 채점 SSE 스트림 URL 생성
 */
export function buildGradeStreamUrl(params: {
  subject: string;
  question: string;
  model_answer: string;
  student_answer: string;
  total_score: number;
  rubric_json?: string;
}): string {
  const query = new URLSearchParams({
    subject: params.subject,
    question: params.question,
    model_answer: params.model_answer,
    student_answer: params.student_answer,
    total_score: String(params.total_score),
    ...(params.rubric_json ? { rubric_json: params.rubric_json } : {}),
  });
  return `${API_URL}/api/grade-stream?${query.toString()}`;
}

/**
 * HITL 교사 결정 제출
 */
export async function submitHitlDecision(
  req: HitlDecisionRequest
): Promise<HitlDecisionResponse> {
  const res = await fetch(`${API_URL}/api/hitl-decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "HITL 결정 제출 실패");
  }
  return res.json();
}
