"use client";

/**
 * GradingProgress — SSE 진행 상태 표시 (4단계 스텝 + 프로그레스바)
 */
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";

interface Step {
  label: string;
  minProgress: number; // 이 단계가 완료되었다고 볼 기준 progress 값
}

const STEPS: Step[] = [
  { label: "루브릭 생성", minProgress: 25 },
  { label: "Rule-base 분석", minProgress: 50 },
  { label: "LLM 독립 평가", minProgress: 75 },
  { label: "의견 조율", minProgress: 100 },
];

interface GradingProgressProps {
  progress: number;       // 0-100
  currentMessage: string;
  status: "streaming" | "hitl_ready" | "completed" | "error";
}

export function GradingProgress({ progress, currentMessage, status }: GradingProgressProps) {
  return (
    <div className="space-y-4">
      {/* 전체 프로그레스바 */}
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>{currentMessage}</span>
          <span>{progress}%</span>
        </div>
        <Progress value={progress} className="h-2" />
      </div>

      {/* 단계별 스텝 표시 */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {STEPS.map((step, idx) => {
          const done = progress >= step.minProgress;
          const active =
            status === "streaming" &&
            progress >= (STEPS[idx - 1]?.minProgress ?? 0) &&
            progress < step.minProgress;

          return (
            <div
              key={step.label}
              className={[
                "flex items-center gap-1.5 rounded-md px-3 py-2 text-xs border",
                done
                  ? "bg-primary/10 border-primary/30 text-primary"
                  : active
                  ? "bg-muted border-border animate-pulse"
                  : "bg-background border-border text-muted-foreground",
              ].join(" ")}
            >
              <span>{done ? "✓" : active ? "⟳" : String(idx + 1)}</span>
              <span>{step.label}</span>
            </div>
          );
        })}
      </div>

      {/* 상태 뱃지 */}
      {status === "hitl_ready" && (
        <Badge variant="outline" className="text-amber-600 border-amber-300">
          교사 검수 대기 중
        </Badge>
      )}
      {status === "completed" && (
        <Badge variant="outline" className="text-green-600 border-green-300">
          채점 완료
        </Badge>
      )}
      {status === "error" && (
        <Badge variant="destructive">오류 발생</Badge>
      )}
    </div>
  );
}
