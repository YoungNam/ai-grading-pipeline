"""
SymPy 수식 동치성 검증 모듈
AST 파싱 → 대수적 동치성(simplify) → 수치 허용 오차(evalf) 순서로 검증
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from sympy import (
    Eq, N, Rational, Symbol, simplify, solve, symbols,
    sympify, zoo, oo, nan,
)
from sympy.core.basic import Basic
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

# ── 파서 설정 ──────────────────────────────────────────────────────────────────
_TRANSFORMATIONS = standard_transformations + (
    implicit_multiplication_application,  # SymPy 1.13+ 대체
    convert_xor,                          # ^ → ** (거듭제곱)
)

_NUMERIC_SAMPLES = 10        # 수치 검증 무작위 샘플 수
_NUMERIC_TOLERANCE = 1e-9    # 허용 절대 오차
_NUMERIC_RANGE = (-5.0, 5.0) # 심볼 대입 범위 (0 근방 제외)


# ── 결과 데이터클래스 ──────────────────────────────────────────────────────────
@dataclass
class VerificationResult:
    is_equivalent: bool
    method: str                          # "algebraic" | "numeric" | "equation" | "error"
    algebraic_diff: Optional[str] = None # simplify 후 차이 표현식
    numeric_pass_rate: Optional[float] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "is_equivalent": self.is_equivalent,
            "method": self.method,
            "algebraic_diff": self.algebraic_diff,
            "numeric_pass_rate": self.numeric_pass_rate,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "details": self.details,
        }


# ── 전처리 유틸 ───────────────────────────────────────────────────────────────
def _preprocess(expr_str: str) -> str:
    """
    학생 답안에서 흔히 발생하는 표기 오류를 SymPy 호환 형식으로 정규화
    예: 2x → 2*x, x² → x**2, ÷ → /
    """
    s = expr_str.strip()
    # 유니코드 위첨자 → **
    superscripts = {"⁰":"0","¹":"1","²":"2","³":"3","⁴":"4",
                    "⁵":"5","⁶":"6","⁷":"7","⁸":"8","⁹":"9"}
    for sup, num in superscripts.items():
        s = s.replace(sup, f"**{num}")
    # ÷ → /
    s = s.replace("÷", "/")
    # × → *
    s = s.replace("×", "*")
    # 분수 표기: a/b 를 그대로 두고 연속 슬래시 방지
    return s


def _safe_parse(expr_str: str, local_dict: Optional[dict] = None) -> tuple[Optional[Basic], Optional[str]]:
    """안전한 파싱. (expr, error_message) 반환"""
    try:
        expr = parse_expr(
            _preprocess(expr_str),
            transformations=_TRANSFORMATIONS,
            local_dict=local_dict or {},
        )
        return expr, None
    except Exception as e:
        return None, f"파싱 오류: {type(e).__name__}: {e}"


def _collect_symbols(expr1: Basic, expr2: Basic) -> list[Symbol]:
    """두 식에서 자유 심볼 수집"""
    return list(expr1.free_symbols | expr2.free_symbols)


# ── 핵심 검증 함수 ────────────────────────────────────────────────────────────
def verify_expression_equivalence(
    student_expr: str,
    model_expr: str,
    tolerance: float = _NUMERIC_TOLERANCE,
) -> VerificationResult:
    """
    두 수식(student_expr, model_expr)의 동치성을 검증합니다.

    검증 순서:
    1. 대수적 동치성: simplify(student - model) == 0
    2. (보완) 수치 동치성: 무작위 값 대입 후 evalf() 비교

    Args:
        student_expr: 학생 답안 수식 문자열 (예: "2*x + 3", "x**2 - 1")
        model_expr:   모범 답안 수식 문자열
        tolerance:    수치 허용 절대 오차 (기본 1e-9)

    Returns:
        VerificationResult
    """
    s_expr, s_err = _safe_parse(student_expr)
    m_expr, m_err = _safe_parse(model_expr)

    if s_expr is None:
        return VerificationResult(
            is_equivalent=False, method="error",
            error_type="ParseError", error_message=s_err,
        )
    if m_expr is None:
        return VerificationResult(
            is_equivalent=False, method="error",
            error_type="ParseError", error_message=m_err,
        )

    # ── 1단계: 대수적 검증 ─────────────────────────────────────────────────────
    try:
        diff = simplify(s_expr - m_expr)
        algebraic_eq = (diff == 0)
        diff_str = str(diff)
    except Exception as e:
        algebraic_eq = False
        diff_str = f"simplify 오류: {e}"

    if algebraic_eq:
        return VerificationResult(
            is_equivalent=True,
            method="algebraic",
            algebraic_diff="0",
            numeric_pass_rate=1.0,
        )

    # ── 2단계: 수치 검증 (대수 검증 실패 시 보완) ─────────────────────────────
    free_syms = _collect_symbols(s_expr, m_expr)
    if not free_syms:
        # 상수식: 수치 직접 비교
        try:
            s_val = float(s_expr.evalf())
            m_val = float(m_expr.evalf())
            is_eq = abs(s_val - m_val) < tolerance
            return VerificationResult(
                is_equivalent=is_eq,
                method="numeric",
                algebraic_diff=diff_str,
                numeric_pass_rate=1.0 if is_eq else 0.0,
                details={"student_val": s_val, "model_val": m_val},
            )
        except Exception as e:
            return VerificationResult(
                is_equivalent=False, method="error",
                error_type="EvalfError", error_message=str(e),
            )

    passes = 0
    lo, hi = _NUMERIC_RANGE
    for _ in range(_NUMERIC_SAMPLES):
        subs = {}
        for sym in free_syms:
            # 0 근방 회피 (분모 0 방지)
            val = random.uniform(lo, hi)
            while abs(val) < 0.1:
                val = random.uniform(lo, hi)
            subs[sym] = Rational(val).limit_denominator(1000)

        try:
            s_val = complex(s_expr.subs(subs).evalf())
            m_val = complex(m_expr.subs(subs).evalf())
            if abs(s_val - m_val) < tolerance:
                passes += 1
        except Exception:
            pass  # 특정 샘플에서 실패 → 건너뜀

    pass_rate = passes / _NUMERIC_SAMPLES
    # 90% 이상 통과 시 동치로 판정 (대수 검증 실패한 경우의 보수적 임계값)
    is_numeric_eq = pass_rate >= 0.9

    return VerificationResult(
        is_equivalent=is_numeric_eq,
        method="numeric",
        algebraic_diff=diff_str,
        numeric_pass_rate=pass_rate,
        details={"samples": _NUMERIC_SAMPLES, "passes": passes},
    )


def verify_equation_equivalence(
    student_eq: str,
    model_eq: str,
    variable: str = "x",
) -> VerificationResult:
    """
    방정식(등식) 형태 "lhs = rhs"의 해집합 동치성 검증
    student_eq, model_eq 모두 '=' 기호 포함 문자열이어야 합니다.

    Args:
        student_eq: 예 "x**2 - 5*x + 6 = 0"
        model_eq:   예 "(x-2)*(x-3) = 0"
        variable:   풀 변수명 (기본 "x")
    """
    def _split_eq(eq_str: str) -> tuple[str, str]:
        parts = eq_str.split("=", 1)
        if len(parts) != 2:
            raise ValueError(f"'=' 기호가 없습니다: {eq_str}")
        return parts[0].strip(), parts[1].strip()

    try:
        sl, sr = _split_eq(student_eq)
        ml, mr = _split_eq(model_eq)
    except ValueError as e:
        return VerificationResult(
            is_equivalent=False, method="error",
            error_type="FormatError", error_message=str(e),
        )

    sym = Symbol(variable, real=True)
    s_lhs, e1 = _safe_parse(sl, {variable: sym})
    s_rhs, e2 = _safe_parse(sr, {variable: sym})
    m_lhs, e3 = _safe_parse(ml, {variable: sym})
    m_rhs, e4 = _safe_parse(mr, {variable: sym})

    for err in [e1, e2, e3, e4]:
        if err:
            return VerificationResult(
                is_equivalent=False, method="error",
                error_type="ParseError", error_message=err,
            )

    try:
        s_solutions = set(map(lambda v: complex(v.evalf()), solve(Eq(s_lhs, s_rhs), sym)))
        m_solutions = set(map(lambda v: complex(v.evalf()), solve(Eq(m_lhs, m_rhs), sym)))
    except Exception as e:
        return VerificationResult(
            is_equivalent=False, method="error",
            error_type="SolveError", error_message=str(e),
        )

    def _round_set(s: set, ndigits: int = 6) -> set:
        return {round(v.real, ndigits) + round(v.imag, ndigits) * 1j for v in s}

    s_rounded = _round_set(s_solutions)
    m_rounded = _round_set(m_solutions)
    is_eq = s_rounded == m_rounded

    return VerificationResult(
        is_equivalent=is_eq,
        method="equation",
        details={
            "student_solutions": [str(v) for v in s_solutions],
            "model_solutions": [str(v) for v in m_solutions],
        },
    )


# ── 통합 진입점 ───────────────────────────────────────────────────────────────
def verify_math(
    student_answer: str,
    model_answer: str,
    variable: str = "x",
) -> VerificationResult:
    """
    수식 or 방정식을 자동 감지하여 적절한 검증 함수 호출.
    '=' 포함 시 방정식, 그 외는 표현식으로 처리.
    """
    s = student_answer.strip()
    m = model_answer.strip()

    has_eq_student = "=" in s and not s.startswith("==")
    has_eq_model = "=" in m and not m.startswith("==")

    if has_eq_student and has_eq_model:
        return verify_equation_equivalence(s, m, variable=variable)
    return verify_expression_equivalence(s, m)


# ── CLI 빠른 테스트 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cases = [
        ("2*x + 4", "2*(x + 2)", "표현식 동치"),
        ("x**2 - 1", "(x-1)*(x+1)", "인수분해 동치"),
        ("x**2 - 5*x + 6 = 0", "(x-2)*(x-3) = 0", "방정식 동치"),
        ("x + 1", "x + 2", "비동치"),
        ("2x + 4", "2*(x+2)", "암시적 곱셈 전처리"),
    ]
    for s, m, label in cases:
        result = verify_math(s, m)
        print(f"[{label}]")
        print(f"  student : {s}")
        print(f"  model   : {m}")
        print(f"  결과    : {'동치 ✓' if result.is_equivalent else '비동치 ✗'} (방법: {result.method})")
        print(f"  상세    : {result.details}")
        print()
