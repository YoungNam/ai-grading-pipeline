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
        {/* Part 1: 기준별 Rule-base 점수 */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-muted-foreground">Part 1 기준별 점수 (0~1 / 항목)</p>
            <span className="text-xs font-bold text-primary">
              합계 {meta.rule_base_total?.toFixed(2) ?? meta.rule_score.toFixed(2)} 점
            </span>
          </div>
          {meta.per_criterion_rule_scores && Object.keys(meta.per_criterion_rule_scores).length > 0 ? (
            <div className="space-y-1">
              {Object.entries(meta.per_criterion_rule_scores).map(([cid, ratio]) => {
                const pct = Math.round(ratio * 100);
                const color = pct >= 80 ? "bg-green-500" : pct >= 40 ? "bg-amber-400" : "bg-red-400";
                return (
                  <div key={cid} className="flex items-center gap-2 text-xs">
                    <span className="font-mono text-muted-foreground w-8 shrink-0">{cid}</span>
                    <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
                    </div>
                    <span className={`w-12 text-right font-medium ${pct >= 80 ? "text-green-600" : pct >= 40 ? "text-amber-500" : "text-red-500"}`}>
                      {ratio.toFixed(2)}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            <ScoreBar value={meta.rule_score} max={meta.rule_max_score} />
          )}
        </div>

        {/* 키워드 매칭 결과 (국어/일반) */}
        {(meta.keyword_hits.length > 0 || meta.keyword_misses.length > 0) && (
          <>
            <Separator />
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">시맨틱 키워드 매칭</p>
              {meta.keyword_hits.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {meta.keyword_hits.map((kw, i) => (
                    <span key={i} className="text-xs bg-green-100 text-green-700 rounded px-1.5 py-0.5">
                      ✓ {kw}
                    </span>
                  ))}
                </div>
              )}
              {meta.keyword_misses.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {meta.keyword_misses.map((kw, i) => (
                    <span key={i} className="text-xs bg-red-100 text-red-600 rounded px-1.5 py-0.5">
                      ✗ {kw}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

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
  const multiModel = models.length > 1;

  // 기준별 루브릭 맵
  const rubricMap = Object.fromEntries(
    rubric?.rubric_items.map((item) => [item.criterion_id, item]) ?? []
  );

  // 기준 ID 목록
  const criterionIds =
    data.evaluator_results[0]?.criterion_scores.map((cs) => cs.criterion_id) ??
    rubric?.rubric_items.map((item) => item.criterion_id) ??
    [];

  // 기준별 Rule 기여점수 (10% × rule_ratio × max_score)
  function getRuleContribution(criterionId: string): number | null {
    const ruleRatio = data.per_criterion_rule_scores[criterionId];
    const maxScore = rubricMap[criterionId]?.max_score;
    if (ruleRatio == null || maxScore == null) return null;
    return Math.round(0.1 * ruleRatio * maxScore * 100) / 100;
  }

  // 기준별 모델 원본 LLM 점수 (original_llm_score 우선, 없으면 adjusted score)
  function getOriginalLlmScore(modelName: string, criterionId: string): number | null {
    const model = data.evaluator_results.find((r) => r.model_name === modelName);
    const cs = model?.criterion_scores.find((c) => c.criterion_id === criterionId);
    return cs?.original_llm_score ?? cs?.score ?? null;
  }

  // 기준별 합산 점수 (90% LLM + 10% Rule, 이미 백엔드에서 계산된 adjusted score 평균)
  // 배점을 초과할 수 없음
  function getCombinedScore(criterionId: string): number {
    const scores = data.evaluator_results
      .map((r) => r.criterion_scores.find((c) => c.criterion_id === criterionId)?.score)
      .filter((s): s is number => s != null);
    if (!scores.length) return 0;
    const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
    const maxScore = rubricMap[criterionId]?.max_score ?? Infinity;
    return Math.round(Math.min(avg, maxScore) * 100) / 100;
  }

  // 2개 이상 모델일 때 기준별 LLM 평균 (원본 점수 기준)
  function getLlmAvgScore(criterionId: string): number | null {
    if (!multiModel) return null;
    const scores = models
      .map((m) => getOriginalLlmScore(m, criterionId))
      .filter((s): s is number => s != null);
    if (!scores.length) return null;
    return Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 100) / 100;
  }

  // 헤더용: Rule 기여 합계 / LLM 기여 합계 (ensemble_score 기준)
  const totalRuleContribution = criterionIds.reduce((sum, cid) => {
    return sum + (getRuleContribution(cid) ?? 0);
  }, 0);
  const totalLlmContribution = Math.round((data.ensemble_score - totalRuleContribution) * 100) / 100;

  // 모델별 합산 레이블 축약
  function modelLabel(name: string) {
    return name.replace("claude-sonnet-", "sonnet-").replace("claude-opus-", "opus-")
      .replace("gpt-4o-mini", "GPT-4o mini").replace("gemini-", "Gem-");
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">AI 앙상블 채점 결과</CardTitle>
          <div className="flex items-center gap-1">
            <span className="text-2xl font-bold text-primary">{data.ensemble_score}</span>
            <span className="text-sm text-muted-foreground">/ {data.total_score}점</span>
          </div>
        </div>
        {/* Rule 기여 / LLM 기여 분해 */}
        <div className="grid grid-cols-2 gap-2 mt-2">
          <div className="rounded-md border px-3 py-2 bg-amber-50">
            <p className="text-xs text-muted-foreground mb-0.5">Rule-base 기여 (10%)</p>
            <p className="text-base font-bold text-amber-600">
              {totalRuleContribution.toFixed(2)}점
            </p>
          </div>
          <div className="rounded-md border px-3 py-2 bg-blue-50">
            <p className="text-xs text-muted-foreground mb-0.5">LLM 기여 (90%)</p>
            <p className="text-base font-bold text-blue-600">
              {totalLlmContribution.toFixed(2)}점
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 기준별 세부 점수 테이블 */}
        {criterionIds.length > 0 && (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">기준</TableHead>
                  <TableHead>평가 기준</TableHead>
                  <TableHead className="w-12 text-right">배점</TableHead>
                  <TableHead className="w-20 text-right text-xs text-amber-600">Rule(10%)</TableHead>
                  {models.map((m) => (
                    <TableHead key={m} className="w-16 text-right text-xs">
                      {modelLabel(m)}
                    </TableHead>
                  ))}
                  {multiModel && (
                    <TableHead className="w-16 text-right text-xs text-muted-foreground">LLM 평균</TableHead>
                  )}
                  <TableHead className="w-16 text-right font-semibold">합산</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {criterionIds.map((cid) => {
                  const rubricItem = rubricMap[cid];
                  const maxScore = rubricItem?.max_score ?? 0;
                  const ruleContrib = getRuleContribution(cid);
                  const ruleRatio = data.per_criterion_rule_scores[cid];
                  const combined = getCombinedScore(cid);
                  const combinedRatio = maxScore > 0 ? combined / maxScore : 0;
                  const llmAvg = getLlmAvgScore(cid);

                  return (
                    <TableRow key={cid}>
                      <TableCell className="font-mono text-xs">{cid}</TableCell>
                      <TableCell className="text-xs max-w-[180px]">
                        <p className="line-clamp-2">{rubricItem?.description ?? "-"}</p>
                      </TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {maxScore || "-"}
                      </TableCell>
                      {/* Rule 기여점수 (10% × ratio × max) */}
                      <TableCell className="text-right text-xs">
                        {ruleContrib != null ? (
                          <span className={ruleRatio >= 0.8 ? "text-green-600" : ruleRatio >= 0.4 ? "text-amber-500" : "text-red-500"}>
                            {ruleContrib.toFixed(2)}
                            <span className="text-muted-foreground ml-0.5 text-[10px]">
                              ({Math.round((ruleRatio ?? 0) * 100)}%)
                            </span>
                          </span>
                        ) : <span className="text-muted-foreground">-</span>}
                      </TableCell>
                      {/* 모델별 원본 LLM 점수 */}
                      {models.map((m) => {
                        const rawScore = getOriginalLlmScore(m, cid);
                        const ratio = maxScore > 0 && rawScore != null ? rawScore / maxScore : null;
                        return (
                          <TableCell key={m} className="text-right text-sm">
                            {rawScore != null ? (
                              <span className={
                                ratio != null && ratio >= 0.8 ? "text-green-600 font-medium" :
                                ratio != null && ratio <= 0.4 ? "text-red-500" : ""
                              }>
                                {rawScore}
                              </span>
                            ) : <span className="text-muted-foreground">-</span>}
                          </TableCell>
                        );
                      })}
                      {/* LLM 평균 (2개 이상 모델일 때) */}
                      {multiModel && (
                        <TableCell className="text-right text-sm text-muted-foreground">
                          {llmAvg ?? "-"}
                        </TableCell>
                      )}
                      {/* 합산 = Rule 10% + LLM 90%, 배점 초과 없음 */}
                      <TableCell className="text-right text-sm font-semibold">
                        <span className={
                          combinedRatio >= 0.8 ? "text-green-600" :
                          combinedRatio <= 0.4 ? "text-red-500" : ""
                        }>
                          {combined.toFixed(2)}
                        </span>
                        <span className="text-muted-foreground text-xs ml-0.5">/{maxScore}</span>
                      </TableCell>
                    </TableRow>
                  );
                })}
                {/* 합계 행 */}
                <TableRow className="border-t-2 font-semibold bg-muted/20">
                  <TableCell colSpan={3} className="text-xs">합계</TableCell>
                  <TableCell className="text-right text-xs text-amber-600">
                    {totalRuleContribution.toFixed(2)}점
                  </TableCell>
                  {data.evaluator_results.map((r) => (
                    <TableCell key={r.model_name} className="text-right text-sm">
                      {(r.original_llm_total ?? r.total_score)}
                    </TableCell>
                  ))}
                  {multiModel && (
                    <TableCell className="text-right text-sm text-muted-foreground">
                      {Math.round(
                        data.evaluator_results.reduce((s, r) => s + (r.original_llm_total ?? r.total_score), 0) /
                        data.evaluator_results.length * 10
                      ) / 10}
                    </TableCell>
                  )}
                  <TableCell className="text-right text-primary font-bold">
                    {data.ensemble_score}점
                  </TableCell>
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

  // Rule 기여 합계: 0.1 × rule_ratio × max_score (점수 단위)
  const rubricMap = Object.fromEntries(
    rubric?.rubric_items.map((item) => [item.criterion_id, item]) ?? []
  );
  const totalRuleContribution = Math.round(
    Object.entries(data.per_criterion_rule_scores).reduce((sum, [cid, ratio]) => {
      const maxScore = rubricMap[cid]?.max_score ?? 0;
      return sum + 0.1 * ratio * maxScore;
    }, 0) * 100
  ) / 100;
  const totalLlmContribution = Math.round((score - totalRuleContribution) * 100) / 100;
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
    const finalRuleContrib = totalRuleContribution;
    const finalLlmContrib = Math.round((finalResult.final_score - finalRuleContrib) * 100) / 100;
    return (
      <Card className="border-green-200 bg-green-50">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-base text-green-800">채점 완료</CardTitle>
            <Badge variant={finalResult.teacher_approved ? "default" : "secondary"}>
              {finalResult.teacher_approved ? "교사 승인" : "교사 수정"}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* 최종 점수 구조 */}
          <div className="grid grid-cols-3 gap-2">
            <div className="text-center">
              <p className="text-xs text-muted-foreground">Rule-base 기여 (10%)</p>
              <p className="text-lg font-bold text-amber-600">{finalRuleContrib.toFixed(2)}점</p>
            </div>
            <div className="text-center">
              <p className="text-xs text-muted-foreground">LLM 기여 (90%)</p>
              <p className="text-lg font-bold text-blue-600">{finalLlmContrib.toFixed(2)}점</p>
            </div>
            <div className="text-center border-l">
              <p className="text-xs text-muted-foreground">최종 합계</p>
              <p className="text-2xl font-bold text-green-700">
                {finalResult.final_score}
                <span className="text-sm font-normal text-green-600 ml-1">/ {data.total_score}점</span>
              </p>
            </div>
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
          {/* 점수 구조 요약 */}
          <div className="rounded-md bg-muted/40 px-3 py-2.5 space-y-1.5 text-sm">
            <div className="flex justify-between items-center">
              <span className="text-muted-foreground text-xs">Rule-base 기여 (10%)</span>
              <span className="font-medium text-amber-600">{totalRuleContribution.toFixed(2)}점</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-muted-foreground text-xs">LLM 기여 (90%)</span>
              <span className="font-medium text-blue-600">{totalLlmContribution.toFixed(2)}점</span>
            </div>
            <Separator className="my-1" />
            <div className="flex justify-between items-center">
              <span className="text-xs font-semibold">예상 최종 합계</span>
              <span className="font-bold text-primary">{score}점 / {data.total_score}점</span>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="score-input">
              최종 점수 조정{" "}
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
