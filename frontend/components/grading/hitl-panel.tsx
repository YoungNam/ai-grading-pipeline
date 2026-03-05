"use client";

/**
 * HitlPanel — 교사 HITL 검수 패널
 *
 * 구성:
 *   1. Rule-base 분석 지표 (키워드 적중/누락, 규칙 점수, 수식 동치성)
 *   2. AI 앙상블 채점 세부 항목 (기준별 모델 점수 테이블 + 모델별 피드백)
 *   3. 교사 검수 (점수 조정 + 피드백 편집 + 승인/수정)
 */
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { type HitlReadyData, type HitlDecision, type FinalResult } from "@/hooks/useAgentStream";
import { type Rubric, type RuleMetadata } from "@/lib/api";

interface HitlPanelProps {
  data: HitlReadyData;
  rubric: Rubric | null;
  onSubmit: (decision: HitlDecision) => Promise<void>;
  finalResult: FinalResult | null;
}

// ── 헬퍼 ─────────────────────────────────────────────────────────────────────

function ScoreBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <Progress value={pct} className="h-2 flex-1" />
      <span className="text-xs text-muted-foreground w-20 text-right">
        {value} / {max}점 ({pct}%)
      </span>
    </div>
  );
}

// ── NLP 지표 카드 헬퍼 ───────────────────────────────────────────────────────

function NlpCard({
  label,
  value,
  tooltip,
}: {
  label: string;
  value: number;
  tooltip?: string;
}) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 70 ? "text-green-600" : pct >= 45 ? "text-amber-500" : "text-red-500";
  return (
    <div className="rounded-md border px-3 py-2 text-center" title={tooltip}>
      <p className="text-xs text-muted-foreground mb-0.5 leading-tight">{label}</p>
      <span className={`text-sm font-bold ${color}`}>{pct}%</span>
    </div>
  );
}

// ── Rule-base 지표 섹션 ───────────────────────────────────────────────────────

// subject_tag → 한국어 라벨
const SUBJECT_LABELS: Record<string, string> = {
  math: "수학",
  korean: "국어",
  science: "과학",
  general: "일반",
};

function RuleMetadataSection({ meta }: { meta: RuleMetadata }) {
  const isMath = meta.subject_tag === "math";
  const isNlp = meta.subject_tag === "korean" || meta.subject_tag === "science";

  // 수학: SymPy 동치성 결과
  const mathEquiv = isMath
    ? (meta.math_equivalence as {
        is_equivalent?: boolean;
        method?: string;
        numeric_pass_rate?: number;
        algebraic_diff?: string;
      } | null)
    : null;

  // 국어/과학: NLP 분석 결과
  const nlpDetail = isNlp
    ? (meta.math_equivalence as {
        // 국어 전용
        criterion_coverage?: number;
        discourse_structure?: number;
        discourse_detail?: Record<string, number>;
        per_criterion_coverage?: Array<{
          criterion_id: string;
          description: string;
          coverage: number;
          max_score: number;
        }>;
        // 과학 전용
        morpheme_overlap?: number;
        keyword_hit_ratio?: number;
        causal_structure_score?: number;
        // 공통
        semantic_similarity?: number;
        model?: string;
      } | null)
    : null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <CardTitle className="text-base">Rule-base 분석 지표</CardTitle>
          <Badge variant="outline" className="text-xs">
            {SUBJECT_LABELS[meta.subject_tag] ?? meta.subject_tag}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 규칙 기반 점수 */}
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">규칙 기반 점수</p>
          <ScoreBar value={meta.rule_score} max={meta.rule_max_score} />
        </div>

        {/* 수학 전용: 수식 동치성 검증 */}
        {mathEquiv && (
          <>
            <Separator />
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">수식 동치성 검증</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <div className="rounded-md border px-3 py-2 text-center">
                  <p className="text-xs text-muted-foreground mb-0.5">결과</p>
                  <span
                    className={`text-sm font-bold ${
                      mathEquiv.is_equivalent ? "text-green-600" : "text-red-500"
                    }`}
                  >
                    {mathEquiv.is_equivalent ? "동치 ✓" : "비동치 ✗"}
                  </span>
                </div>
                <div className="rounded-md border px-3 py-2 text-center">
                  <p className="text-xs text-muted-foreground mb-0.5">검증 방법</p>
                  <span className="text-sm font-medium">{mathEquiv.method ?? "-"}</span>
                </div>
                {mathEquiv.numeric_pass_rate != null && (
                  <div className="rounded-md border px-3 py-2 text-center">
                    <p className="text-xs text-muted-foreground mb-0.5">수치 통과율</p>
                    <span className="text-sm font-medium">
                      {Math.round(mathEquiv.numeric_pass_rate * 100)}%
                    </span>
                  </div>
                )}
                {mathEquiv.algebraic_diff && mathEquiv.algebraic_diff !== "0" && (
                  <div className="rounded-md border px-3 py-2 text-center col-span-2 sm:col-span-1">
                    <p className="text-xs text-muted-foreground mb-0.5">대수 차이</p>
                    <span className="text-sm font-mono">{mathEquiv.algebraic_diff}</span>
                  </div>
                )}
              </div>
            </div>
          </>
        )}

        {/* 국어/과학 전용: NLP 분석 지표 */}
        {nlpDetail && (
          <>
            <Separator />
            <div className="space-y-3">
              <p className="text-xs font-medium text-muted-foreground">
                NLP 분석 지표
                <span className="ml-1 font-normal text-muted-foreground/70">
                  ({nlpDetail.model ?? "Sentence-BERT"})
                </span>
              </p>

              {/* 공통: 의미 유사도 */}
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {nlpDetail.semantic_similarity != null && (
                  <NlpCard
                    label="모범답안 의미 유사도"
                    value={nlpDetail.semantic_similarity}
                    tooltip="학생 답안 전체와 모범 답안의 SBERT 코사인 유사도"
                  />
                )}

                {/* 국어 전용 지표 */}
                {meta.subject_tag === "korean" && (
                  <>
                    {nlpDetail.criterion_coverage != null && (
                      <NlpCard
                        label="루브릭 기준 커버리지"
                        value={nlpDetail.criterion_coverage}
                        tooltip="각 평가 기준을 학생 답안이 얼마나 의미적으로 충족했는지 (가중 평균)"
                      />
                    )}
                    {nlpDetail.discourse_structure != null && (
                      <NlpCard
                        label="논리 구조 표현"
                        value={nlpDetail.discourse_structure}
                        tooltip="주장·근거·결론 구조 표현 여부"
                      />
                    )}
                  </>
                )}

                {/* 과학 전용 지표 */}
                {meta.subject_tag === "science" && (
                  <>
                    {nlpDetail.morpheme_overlap != null && (
                      <NlpCard
                        label="전문 용어 겹침률"
                        value={nlpDetail.morpheme_overlap}
                        tooltip="모범 답안의 핵심 전문 용어 중 학생이 사용한 비율 (Recall)"
                      />
                    )}
                    {nlpDetail.keyword_hit_ratio != null && (
                      <NlpCard
                        label="키워드 적중률"
                        value={nlpDetail.keyword_hit_ratio}
                        tooltip="루브릭 키워드 정확 매칭 비율"
                      />
                    )}
                    {nlpDetail.causal_structure_score != null && (
                      <NlpCard
                        label="인과 구조"
                        value={nlpDetail.causal_structure_score}
                        tooltip="원인-결과 설명 표현 사용 여부"
                      />
                    )}
                  </>
                )}
              </div>

              {/* 국어 전용: 루브릭 기준별 커버리지 상세 */}
              {meta.subject_tag === "korean" &&
                nlpDetail.per_criterion_coverage &&
                nlpDetail.per_criterion_coverage.length > 0 && (
                  <details>
                    <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground select-none">
                      기준별 커버리지 상세 ({nlpDetail.per_criterion_coverage.length}개 항목)
                    </summary>
                    <div className="mt-2 space-y-1">
                      {nlpDetail.per_criterion_coverage.map((item) => {
                        const pct = Math.round(item.coverage * 100);
                        const color =
                          pct >= 70
                            ? "text-green-600"
                            : pct >= 45
                            ? "text-amber-500"
                            : "text-red-500";
                        return (
                          <div
                            key={item.criterion_id}
                            className="flex items-center gap-2 text-xs"
                          >
                            <span className="font-mono text-muted-foreground w-8 shrink-0">
                              {item.criterion_id}
                            </span>
                            <div className="flex-1 min-w-0">
                              <p className="truncate text-muted-foreground">
                                {item.description}
                              </p>
                              <div className="flex items-center gap-1.5 mt-0.5">
                                <div className="flex-1 h-1 rounded-full bg-muted overflow-hidden">
                                  <div
                                    className={`h-full rounded-full ${
                                      pct >= 70
                                        ? "bg-green-500"
                                        : pct >= 45
                                        ? "bg-amber-400"
                                        : "bg-red-400"
                                    }`}
                                    style={{ width: `${pct}%` }}
                                  />
                                </div>
                                <span className={`font-medium w-8 text-right ${color}`}>
                                  {pct}%
                                </span>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </details>
                )}

              {/* 국어 전용: 논리 구조 카테고리별 */}
              {meta.subject_tag === "korean" && nlpDetail.discourse_detail && (
                <details>
                  <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground select-none">
                    논리 구조 세부 항목
                  </summary>
                  <div className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-5">
                    {(
                      [
                        ["evidence", "근거 제시"],
                        ["claim", "주장 표현"],
                        ["conclusion", "결론 도출"],
                        ["elaboration", "내용 전개"],
                        ["concession", "반론 인정"],
                      ] as const
                    ).map(([key, label]) => {
                      const v = nlpDetail.discourse_detail?.[key] ?? 0;
                      const pct = Math.round(v * 100);
                      return (
                        <div
                          key={key}
                          className="rounded-md border px-2 py-1.5 text-center"
                        >
                          <p className="text-xs text-muted-foreground mb-0.5">{label}</p>
                          <span
                            className={`text-sm font-bold ${
                              pct >= 100
                                ? "text-green-600"
                                : pct > 0
                                ? "text-amber-500"
                                : "text-muted-foreground"
                            }`}
                          >
                            {pct >= 100 ? "✓" : pct > 0 ? "△" : "✗"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </details>
              )}
            </div>
          </>
        )}

      </CardContent>
    </Card>
  );
}

// ── 앙상블 세부 항목 섹션 ─────────────────────────────────────────────────────

function EnsembleDetailSection({
  data,
  rubric,
}: {
  data: HitlReadyData;
  rubric: Rubric | null;
}) {
  const models = data.evaluator_results.map((r) => r.model_name);

  // 기준별 루브릭 맵 (description, max_score 조회용)
  const rubricMap = Object.fromEntries(
    rubric?.rubric_items.map((item) => [item.criterion_id, item]) ?? []
  );

  // 기준 ID 목록 (첫 번째 모델 기준으로 수집, 없으면 rubric에서)
  const criterionIds =
    data.evaluator_results[0]?.criterion_scores.map((cs) => cs.criterion_id) ??
    rubric?.rubric_items.map((item) => item.criterion_id) ??
    [];

  // 기준별 모델 점수 조회 함수
  function getScore(modelName: string, criterionId: string): number | null {
    const model = data.evaluator_results.find((r) => r.model_name === modelName);
    const cs = model?.criterion_scores.find((c) => c.criterion_id === criterionId);
    return cs?.score ?? null;
  }

  // 기준별 평균 점수
  function getAvgScore(criterionId: string): number {
    const scores = data.evaluator_results
      .map((r) => r.criterion_scores.find((c) => c.criterion_id === criterionId)?.score)
      .filter((s): s is number => s != null);
    if (scores.length === 0) return 0;
    return Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 10) / 10;
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">AI 앙상블 채점 결과</CardTitle>
          <div className="flex items-center gap-1.5">
            <span className="text-2xl font-bold">{data.ensemble_score}</span>
            <span className="text-sm text-muted-foreground">/ {data.total_score}점</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 모델별 총점 */}
        <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${models.length}, 1fr)` }}>
          {data.evaluator_results.map((r) => (
            <div
              key={r.model_name}
              className="rounded-md border px-3 py-2.5 text-center bg-muted/30"
            >
              <p className="text-xs text-muted-foreground truncate mb-1">{r.model_name}</p>
              <p className="text-lg font-bold">
                {r.total_score}
                <span className="text-xs text-muted-foreground font-normal ml-0.5">
                  /{data.total_score}
                </span>
              </p>
            </div>
          ))}
        </div>

        {/* 기준별 세부 점수 테이블 */}
        {criterionIds.length > 0 && (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">기준</TableHead>
                  <TableHead>평가 기준</TableHead>
                  <TableHead className="w-14 text-right">배점</TableHead>
                  {models.map((m) => (
                    <TableHead key={m} className="w-16 text-right text-xs">
                      {m.replace("claude-", "").replace("gpt-", "GPT-").replace("gemini-", "Gem-")}
                    </TableHead>
                  ))}
                  <TableHead className="w-14 text-right">평균</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {criterionIds.map((cid) => {
                  const rubricItem = rubricMap[cid];
                  const avgScore = getAvgScore(cid);
                  const maxScore = rubricItem?.max_score ?? "-";
                  const hitRate =
                    typeof maxScore === "number" && maxScore > 0
                      ? avgScore / maxScore
                      : null;

                  return (
                    <TableRow key={cid}>
                      <TableCell className="font-mono text-xs">{cid}</TableCell>
                      <TableCell className="text-xs max-w-[200px]">
                        <p className="line-clamp-2">{rubricItem?.description ?? "-"}</p>
                      </TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {maxScore}
                      </TableCell>
                      {models.map((m) => {
                        const score = getScore(m, cid);
                        return (
                          <TableCell key={m} className="text-right text-sm">
                            {score != null ? (
                              <span
                                className={
                                  hitRate != null && score / (rubricItem?.max_score ?? 1) >= 0.8
                                    ? "text-green-600 font-medium"
                                    : hitRate != null && score / (rubricItem?.max_score ?? 1) <= 0.4
                                    ? "text-red-500"
                                    : ""
                                }
                              >
                                {score}
                              </span>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </TableCell>
                        );
                      })}
                      <TableCell className="text-right text-sm font-medium">{avgScore}</TableCell>
                    </TableRow>
                  );
                })}
                {/* 합계 행 */}
                <TableRow className="border-t-2 font-semibold bg-muted/20">
                  <TableCell colSpan={3} className="text-xs">
                    합계
                  </TableCell>
                  {data.evaluator_results.map((r) => (
                    <TableCell key={r.model_name} className="text-right">
                      {r.total_score}
                    </TableCell>
                  ))}
                  <TableCell className="text-right text-primary">{data.ensemble_score}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>
        )}

        {/* 모델별 피드백 */}
        <details>
          <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground select-none">
            모델별 상세 피드백 ({data.evaluator_results.length}건)
          </summary>
          <div className="mt-2 space-y-2">
            {data.evaluator_results.map((r) => (
              <div key={r.model_name} className="rounded-md border p-3 bg-muted/20">
                <p className="text-xs font-medium mb-1 text-muted-foreground">{r.model_name}</p>
                <p className="text-xs whitespace-pre-wrap">{r.feedback}</p>
              </div>
            ))}
          </div>
        </details>

        {/* 토론 로그 */}
        {data.debate_log.length > 0 && (
          <details>
            <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground select-none">
              점수 조율 토론 로그 ({data.debate_log.length}건)
            </summary>
            <ul className="mt-2 space-y-1">
              {data.debate_log.map((log, i) => (
                <li key={i} className="text-xs text-muted-foreground pl-2 border-l">
                  {log}
                </li>
              ))}
            </ul>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────────────────────

export function HitlPanel({ data, rubric, onSubmit, finalResult }: HitlPanelProps) {
  const [feedback, setFeedback] = useState(data.ensemble_feedback ?? "");
  const [score, setScore] = useState<number>(data.ensemble_score ?? 0);
  const [correctionNote, setCorrectionNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDecision(approved: boolean) {
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit({
        approved,
        corrected_score: approved ? undefined : score,
        corrected_feedback: approved ? undefined : feedback,
        correction_note: correctionNote,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "제출 실패");
    } finally {
      setSubmitting(false);
    }
  }

  // 최종 결과 표시
  if (finalResult) {
    return (
      <Card className="border-green-200 bg-green-50">
        <CardHeader>
          <CardTitle className="text-base text-green-800">채점 완료</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3">
            <span className="text-3xl font-bold text-green-700">{finalResult.final_score}</span>
            <span className="text-muted-foreground">/ {data.total_score}점</span>
            <Badge variant={finalResult.teacher_approved ? "default" : "secondary"}>
              {finalResult.teacher_approved ? "교사 승인" : "교사 수정"}
            </Badge>
          </div>
          <Separator />
          <div>
            <p className="text-xs text-muted-foreground mb-1">최종 피드백</p>
            <p className="text-sm whitespace-pre-wrap">{finalResult.final_feedback}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* 섹션 1: Rule-base 분석 지표 */}
      {data.rule_metadata && <RuleMetadataSection meta={data.rule_metadata} />}

      {/* 섹션 2: AI 앙상블 채점 세부 항목 */}
      <EnsembleDetailSection data={data} rubric={rubric} />

      {/* 섹션 3: 교사 검수 */}
      <Card className="border-amber-200">
        <CardHeader className="pb-2">
          <CardTitle className="text-base text-amber-800">교사 검수</CardTitle>
          <p className="text-xs text-muted-foreground">
            점수와 피드백을 확인 후 승인하거나 수정하세요.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="score-input">
              점수 조정{" "}
              <span className="text-muted-foreground text-xs">(0 ~ {data.total_score})</span>
            </Label>
            <Input
              id="score-input"
              type="number"
              min={0}
              max={data.total_score}
              step={0.5}
              value={score}
              onChange={(e) => setScore(Number(e.target.value))}
              className="w-32"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="feedback-input">종합 피드백</Label>
            <Textarea
              id="feedback-input"
              rows={5}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="note-input">수정 사유 (선택)</Label>
            <Input
              id="note-input"
              placeholder="예) 풀이 과정 부분 점수 조정"
              value={correctionNote}
              onChange={(e) => setCorrectionNote(e.target.value)}
            />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <div className="flex gap-2">
            <Button onClick={() => handleDecision(true)} disabled={submitting} className="flex-1">
              승인 (AI 결과 그대로)
            </Button>
            <Button
              variant="outline"
              onClick={() => handleDecision(false)}
              disabled={submitting}
              className="flex-1"
            >
              수정 후 제출
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
