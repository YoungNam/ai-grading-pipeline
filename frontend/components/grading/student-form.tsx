"use client";

/**
 * StudentForm — 학생 답안 입력 + 채점 시작
 */
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { type GradingParams } from "@/hooks/useAgentStream";

interface StudentFormProps {
  defaultParams?: Partial<GradingParams>;
  disabled?: boolean;
  onStart: (params: GradingParams) => void;
}

export function StudentForm({ defaultParams, disabled, onStart }: StudentFormProps) {
  const [studentAnswer, setStudentAnswer] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!studentAnswer.trim()) return;
    onStart({
      subject: defaultParams?.subject ?? "auto",
      question: defaultParams?.question ?? "",
      model_answer: defaultParams?.model_answer ?? "",
      total_score: defaultParams?.total_score ?? 10,
      student_answer: studentAnswer.trim(),
      rubric_json: defaultParams?.rubric_json,
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">학생 답안 입력</CardTitle>
      </CardHeader>
      <CardContent>
        {/* 문항 미리보기 */}
        {defaultParams?.question && (
          <div className="mb-4 p-3 bg-muted rounded-md text-sm">
            <p className="text-muted-foreground text-xs mb-1">평가 문항</p>
            <p>{defaultParams.question}</p>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="student-answer">학생 답안</Label>
            <Textarea
              id="student-answer"
              placeholder="학생의 답안을 입력하세요..."
              rows={6}
              value={studentAnswer}
              onChange={(e) => setStudentAnswer(e.target.value)}
              disabled={disabled}
              required
            />
          </div>
          <Button type="submit" disabled={disabled || !studentAnswer.trim()} className="w-full">
            채점 시작
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
