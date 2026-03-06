"use client";

/**
 * useAgentStream — SSE 채점 스트림 커스텀 훅
 *
 * 사용 흐름:
 *   1. startGrading() → EventSource 연결 → SSE 이벤트마다 state 업데이트
 *   2. hitl_ready 이벤트 수신 → status = "hitl_ready"로 전환
 *   3. submitHitlDecision() → POST /api/hitl-decision → status = "completed"
 */
import { useCallback, useRef, useState } from "react";
import {
  type EvaluatorResult,
  type Rubric,
  type RuleMetadata,
  type SSEEventData,
  buildGradeStreamUrl,
  submitHitlDecision as apiSubmitHitl,
} from "@/lib/api";

// ── 타입 ─────────────────────────────────────────────────────────────────────

export interface HitlReadyData {
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

export interface FinalResult {
  thread_id: string;
  teacher_approved: boolean;
  final_score: number;
  final_feedback: string;
}

export interface HitlDecision {
  approved: boolean;
  corrected_score?: number;
  corrected_feedback?: string;
  correction_note?: string;
}

export interface GradingParams {
  subject: string;
  question: string;
  model_answer: string;
  student_answer: string;
  total_score: number;
  rubric_json?: string;
}

interface AgentStreamState {
  status: "idle" | "streaming" | "hitl_ready" | "completed" | "error";
  progress: number;
  currentMessage: string;
  threadId: string | null;
  rubric: Rubric | null;
  ruleMetadata: RuleMetadata | null;
  hitlData: HitlReadyData | null;
  finalResult: FinalResult | null;
  error: string | null;
}

const INITIAL_STATE: AgentStreamState = {
  status: "idle",
  progress: 0,
  currentMessage: "",
  threadId: null,
  rubric: null,
  ruleMetadata: null,
  hitlData: null,
  finalResult: null,
  error: null,
};

// ── 훅 ───────────────────────────────────────────────────────────────────────

export function useAgentStream() {
  const [state, setState] = useState<AgentStreamState>(INITIAL_STATE);
  const esRef = useRef<EventSource | null>(null);

  /**
   * 채점 SSE 스트림 시작
   */
  const startGrading = useCallback((params: GradingParams) => {
    // 기존 연결 종료
    if (esRef.current) {
      esRef.current.close();
    }

    setState({ ...INITIAL_STATE, status: "streaming", currentMessage: "채점 시작 중..." });

    const url = buildGradeStreamUrl(params);
    const es = new EventSource(url);
    esRef.current = es;

    es.onmessage = (event) => {
      try {
        const data: SSEEventData = JSON.parse(event.data);
        handleSSEEvent(data);
      } catch {
        // 파싱 오류 무시
      }
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      setState((prev) =>
        prev.status === "hitl_ready" || prev.status === "completed"
          ? prev // hitl_ready / completed 상태에서는 연결 종료가 정상
          : { ...prev, status: "error", error: "서버 연결이 끊어졌습니다." }
      );
    };
  }, []);

  /**
   * SSE 이벤트 핸들러
   */
  function handleSSEEvent(data: SSEEventData) {
    switch (data.type) {
      case "started":
        setState((prev) => ({ ...prev, threadId: data.thread_id }));
        break;

      case "progress":
        setState((prev) => ({
          ...prev,
          progress: data.progress,
          currentMessage: data.message,
        }));
        break;

      case "rubric_done":
        setState((prev) => ({ ...prev, rubric: data.rubric }));
        break;

      case "rule_done":
        setState((prev) => ({ ...prev, ruleMetadata: data.rule_metadata }));
        break;

      case "hitl_ready": {
        const hitlData: HitlReadyData = {
          thread_id: data.thread_id,
          ensemble_score: data.ensemble_score,
          ensemble_feedback: data.ensemble_feedback,
          grand_total: data.grand_total ?? null,
          rule_base_total: data.rule_base_total ?? 0,
          per_criterion_rule_scores: data.per_criterion_rule_scores ?? {},
          total_score: data.total_score,
          evaluator_results: data.evaluator_results,
          debate_log: data.debate_log,
          rule_metadata: data.rule_metadata,
        };
        // hitl_ready 상태에서 SSE 연결은 자연스럽게 종료됨
        esRef.current?.close();
        esRef.current = null;
        setState((prev) => ({
          ...prev,
          status: "hitl_ready",
          progress: 100,
          currentMessage: "교사 검수 대기 중",
          hitlData,
        }));
        break;
      }

      case "error":
        esRef.current?.close();
        esRef.current = null;
        setState((prev) => ({
          ...prev,
          status: "error",
          error: data.message,
        }));
        break;
    }
  }

  /**
   * HITL 교사 결정 제출
   */
  const submitHitlDecision = useCallback(
    async (decision: HitlDecision) => {
      const threadId = state.threadId;
      if (!threadId) throw new Error("thread_id 없음");

      const result = await apiSubmitHitl({
        thread_id: threadId,
        ...decision,
      });

      setState((prev) => ({
        ...prev,
        status: "completed",
        finalResult: result,
      }));

      return result;
    },
    [state.threadId]
  );

  /**
   * 상태 초기화
   */
  const reset = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    setState(INITIAL_STATE);
  }, []);

  return { state, startGrading, submitHitlDecision, reset };
}
