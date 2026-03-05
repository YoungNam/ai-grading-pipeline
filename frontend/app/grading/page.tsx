"use client";

/**
 * /grading 페이지 — 학생 답안 채점 + HITL 검수
 * sessionStorage에서 루브릭 로드 (setup 화면에서 전달)
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { StudentForm } from "@/components/grading/student-form";
import { GradingProgress } from "@/components/grading/grading-progress";
import { HitlPanel } from "@/components/grading/hitl-panel";
import { useAgentStream, type GradingParams } from "@/hooks/useAgentStream";
import { type Rubric } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export default function GradingPage() {
  const router = useRouter();
  const { state, startGrading, submitHitlDecision, reset } = useAgentStream();
  const [savedRubric, setSavedRubric] = useState<Rubric | null>(null);
  const [gradingParams, setGradingParams] = useState<Partial<GradingParams>>({});

  // sessionStorage에서 루브릭 + 과목·문항·모범답안 로드
  useEffect(() => {
    const rawRubric = sessionStorage.getItem("current_rubric");
    const rawMeta = sessionStorage.getItem("current_form_meta");
    if (rawRubric) {
      try {
        const rubric: Rubric = JSON.parse(rawRubric);
        const meta = rawMeta ? JSON.parse(rawMeta) : null;
        setSavedRubric(rubric);
        setGradingParams({
          subject: meta?.subject ?? "auto",
          question: meta?.question ?? rubric.task_description,
          model_answer: meta?.model_answer ?? "",
          total_score: meta?.total_score ?? rubric.total_score,
          rubric_json: rawRubric,
        });
      } catch {
        // 파싱 실패 시 무시
      }
    }
  }, []);

  function handleStart(params: GradingParams) {
    startGrading(params);
  }

  function handleReset() {
    reset();
  }

  const isStreaming = state.status === "streaming";
  const showProgress = state.status !== "idle";

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">학생 답안 검수</h2>
          <p className="text-sm text-muted-foreground mt-1">
            학생 답안을 입력하면 AI가 채점 후 교사 검수 단계로 넘어갑니다.
          </p>
        </div>
        {state.status !== "idle" && (
          <Button variant="ghost" size="sm" onClick={handleReset}>
            초기화
          </Button>
        )}
      </div>

      {/* 루브릭 없음 경고 */}
      {!savedRubric && (
        <Card className="border-amber-200 bg-amber-50">
          <CardContent className="pt-4 pb-4 flex items-center justify-between">
            <p className="text-sm text-amber-800">
              루브릭이 설정되지 않았습니다. 먼저 문항을 설정해 주세요.
            </p>
            <Button size="sm" variant="outline" onClick={() => router.push("/setup")}>
              문항 설정으로 이동
            </Button>
          </CardContent>
        </Card>
      )}

      {/* 학생 답안 입력 폼 */}
      {(state.status === "idle" || state.status === "error") && (
        <StudentForm
          defaultParams={gradingParams}
          disabled={isStreaming}
          onStart={handleStart}
        />
      )}

      {/* 오류 메시지 */}
      {state.status === "error" && state.error && (
        <Card className="border-destructive bg-destructive/5">
          <CardContent className="pt-4 pb-4">
            <p className="text-sm text-destructive">오류: {state.error}</p>
          </CardContent>
        </Card>
      )}

      {/* 채점 진행 표시 */}
      {showProgress && state.status !== "idle" && (
        <Card>
          <CardContent className="pt-4 pb-4">
            <GradingProgress
              progress={state.progress}
              currentMessage={state.currentMessage}
              status={state.status === "error" ? "error" : state.status === "streaming" ? "streaming" : state.status === "hitl_ready" ? "hitl_ready" : "completed"}
            />
          </CardContent>
        </Card>
      )}

      {/* HITL 패널 */}
      {(state.status === "hitl_ready" || state.status === "completed") &&
        state.hitlData && (
          <HitlPanel
            data={state.hitlData}
            rubric={state.rubric}
            onSubmit={async (decision) => { await submitHitlDecision(decision); }}
            finalResult={state.finalResult}
          />
        )}
    </div>
  );
}
