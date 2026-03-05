"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { EvaluationForm, type FormMeta } from "@/components/rubric/evaluation-form";
import { RubricTable } from "@/components/rubric/rubric-table";
import { type Rubric } from "@/lib/api";

export default function SetupPage() {
  const router = useRouter();
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [formMeta, setFormMeta] = useState<FormMeta | null>(null);

  function handleRubricGenerated(newRubric: Rubric, meta: FormMeta) {
    setRubric(newRubric);
    setFormMeta(meta);
  }

  function handleStartGrading() {
    if (!rubric || !formMeta) return;
    // 루브릭 + 과목·문항·모범답안 전체를 sessionStorage에 저장
    sessionStorage.setItem("current_rubric", JSON.stringify(rubric));
    sessionStorage.setItem("current_form_meta", JSON.stringify(formMeta));
    router.push("/grading");
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h2 className="text-xl font-semibold">문항 및 루브릭 세팅</h2>
        <p className="text-sm text-muted-foreground mt-1">
          평가 문항과 모범 답안을 입력하면 AI가 Bloom&apos;s Taxonomy 기반 루브릭을 생성합니다.
          생성 후 셀을 클릭하여 직접 편집할 수 있습니다.
        </p>
      </div>

      <EvaluationForm onRubricGenerated={handleRubricGenerated} />

      {rubric && (
        <RubricTable
          rubric={rubric}
          onRubricChange={setRubric}
          onStartGrading={handleStartGrading}
        />
      )}
    </div>
  );
}
