"use client";

/**
 * EvaluationForm — 루브릭 생성을 위한 문항 입력 폼
 */
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { generateRubric, type Rubric } from "@/lib/api";

export interface FormMeta {
  subject: string;
  question: string;
  model_answer: string;
  total_score: number;
}

interface EvaluationFormProps {
  onRubricGenerated: (rubric: Rubric, meta: FormMeta) => void;
}

const SUBJECTS = [
  { value: "auto", label: "자동 감지" },
  { value: "math", label: "수학" },
  { value: "korean", label: "국어" },
  { value: "science", label: "과학" },
  { value: "general", label: "일반" },
];

export function EvaluationForm({ onRubricGenerated }: EvaluationFormProps) {
  const [subject, setSubject] = useState("auto");
  const [question, setQuestion] = useState("");
  const [modelAnswer, setModelAnswer] = useState("");
  const [totalScore, setTotalScore] = useState<number>(10);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim() || !modelAnswer.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const result = await generateRubric({
        subject,
        question: question.trim(),
        model_answer: modelAnswer.trim(),
        total_score: totalScore,
      });
      onRubricGenerated(result.rubric, {
        subject,
        question: question.trim(),
        model_answer: modelAnswer.trim(),
        total_score: totalScore,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "루브릭 생성 실패");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">문항 정보 입력</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* 과목 + 총점 */}
          <div className="flex gap-4">
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="subject">과목</Label>
              <Select value={subject} onValueChange={setSubject}>
                <SelectTrigger id="subject">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SUBJECTS.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-28 space-y-1.5">
              <Label htmlFor="total-score">총점</Label>
              <Input
                id="total-score"
                type="number"
                min={1}
                max={100}
                value={totalScore}
                onChange={(e) => setTotalScore(Number(e.target.value))}
              />
            </div>
          </div>

          {/* 문항 */}
          <div className="space-y-1.5">
            <Label htmlFor="question">평가 문항</Label>
            <Textarea
              id="question"
              placeholder="예) 이차방정식 x² - 5x + 6 = 0을 풀어라."
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              required
            />
          </div>

          {/* 모범 답안 */}
          <div className="space-y-1.5">
            <Label htmlFor="model-answer">모범 답안</Label>
            <Textarea
              id="model-answer"
              placeholder="예) (x-2)(x-3) = 0이므로 x = 2 또는 x = 3"
              rows={4}
              value={modelAnswer}
              onChange={(e) => setModelAnswer(e.target.value)}
              required
            />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <Button type="submit" disabled={loading} className="w-full">
            {loading ? "루브릭 생성 중..." : "루브릭 생성"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
