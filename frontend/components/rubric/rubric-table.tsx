"use client";

/**
 * RubricTable — 루브릭 인라인 편집 테이블
 * 셀 클릭 시 input/textarea로 전환, Enter/blur 시 저장
 */
import { useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { type Rubric, type RubricItem } from "@/lib/api";

interface RubricTableProps {
  rubric: Rubric;
  onRubricChange: (rubric: Rubric) => void;
  onStartGrading?: () => void;
}

// 편집 중인 셀 위치
type EditingCell = { rowIdx: number; field: keyof RubricItem } | null;

export function RubricTable({ rubric, onRubricChange, onStartGrading }: RubricTableProps) {
  const [editingCell, setEditingCell] = useState<EditingCell>(null);
  const [editValue, setEditValue] = useState("");

  function startEdit(rowIdx: number, field: keyof RubricItem, value: string) {
    setEditingCell({ rowIdx, field });
    setEditValue(value);
  }

  function commitEdit() {
    if (!editingCell) return;
    const { rowIdx, field } = editingCell;
    const updatedItems = rubric.rubric_items.map((item, idx) => {
      if (idx !== rowIdx) return item;
      const updated = { ...item };
      if (field === "max_score") {
        updated.max_score = Number(editValue) || item.max_score;
      } else if (field === "keywords") {
        updated.keywords = editValue.split(",").map((k) => k.trim()).filter(Boolean);
      } else {
        (updated as Record<string, unknown>)[field] = editValue;
      }
      return updated;
    });
    onRubricChange({ ...rubric, rubric_items: updatedItems });
    setEditingCell(null);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      commitEdit();
    } else if (e.key === "Escape") {
      setEditingCell(null);
    }
  }

  function EditableCell({
    rowIdx,
    field,
    value,
    multiline = false,
  }: {
    rowIdx: number;
    field: keyof RubricItem;
    value: string;
    multiline?: boolean;
  }) {
    const isEditing = editingCell?.rowIdx === rowIdx && editingCell?.field === field;

    if (isEditing) {
      if (multiline) {
        return (
          <textarea
            autoFocus
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={commitEdit}
            onKeyDown={handleKeyDown}
            className="w-full resize-none text-sm bg-background border rounded px-1 py-0.5 min-h-[60px]"
          />
        );
      }
      return (
        <input
          autoFocus
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={handleKeyDown}
          className="w-full text-sm bg-background border rounded px-1 py-0.5"
        />
      );
    }

    return (
      <span
        onClick={() => startEdit(rowIdx, field, value)}
        className="cursor-pointer rounded px-1 py-0.5 hover:bg-accent block min-w-[40px] min-h-[24px]"
        title="클릭하여 편집"
      >
        {value}
      </span>
    );
  }

  const scoreSum = rubric.rubric_items.reduce((sum, item) => sum + item.max_score, 0);
  const scoreMismatch = scoreSum !== rubric.total_score;

  return (
    <div className="space-y-3">
      {/* 루브릭 메타 정보 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">생성된 루브릭</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex flex-wrap gap-2">
            <span className="text-muted-foreground">문항 요약:</span>
            <span>{rubric.task_description}</span>
          </div>
          <div className="flex gap-4">
            <span>
              <span className="text-muted-foreground mr-1">인지 수준:</span>
              <Badge variant="secondary">{rubric.cognitive_level}</Badge>
            </span>
            <span>
              <span className="text-muted-foreground mr-1">총점:</span>
              <span className={scoreMismatch ? "text-destructive font-bold" : ""}>
                {scoreSum} / {rubric.total_score}
                {scoreMismatch && " ⚠ 배점 불일치"}
              </span>
            </span>
          </div>
        </CardContent>
      </Card>

      {/* 루브릭 항목 테이블 */}
      <Card>
        <CardContent className="pt-4 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">ID</TableHead>
                <TableHead>평가 기준</TableHead>
                <TableHead className="w-20">배점</TableHead>
                <TableHead className="w-28">블룸 수준</TableHead>
                <TableHead>키워드 (쉼표 구분)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rubric.rubric_items.map((item, idx) => (
                <TableRow key={item.criterion_id}>
                  <TableCell className="font-mono text-xs">{item.criterion_id}</TableCell>
                  <TableCell>
                    <EditableCell
                      rowIdx={idx}
                      field="description"
                      value={item.description}
                      multiline
                    />
                  </TableCell>
                  <TableCell>
                    <EditableCell
                      rowIdx={idx}
                      field="max_score"
                      value={String(item.max_score)}
                    />
                  </TableCell>
                  <TableCell>
                    <EditableCell
                      rowIdx={idx}
                      field="bloom_level"
                      value={item.bloom_level}
                    />
                  </TableCell>
                  <TableCell>
                    <EditableCell
                      rowIdx={idx}
                      field="keywords"
                      value={item.keywords.join(", ")}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* 채점 시작 버튼 */}
      {onStartGrading && (
        <Button
          onClick={onStartGrading}
          className="w-full"
          disabled={scoreMismatch}
        >
          이 루브릭으로 채점 화면으로 이동
        </Button>
      )}
    </div>
  );
}
