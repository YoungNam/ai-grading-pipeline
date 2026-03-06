#!/usr/bin/env python3
"""
시크릿 관리 CLI — API 키를 .env.enc에 암호화 저장

사용법:
  python3 scripts/manage_secrets.py init      # MASTER_KEY 신규 발급
  python3 scripts/manage_secrets.py set       # 키 추가/수정 (입력값 화면 미표시)
  python3 scripts/manage_secrets.py list      # 저장된 키 이름 목록 확인
  python3 scripts/manage_secrets.py delete    # 특정 키 삭제
  python3 scripts/manage_secrets.py export    # 클라우드용 환경변수 출력 (값 마스킹)
"""
from __future__ import annotations

import getpass
import os
import sys

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PROJECT_ROOT)

_ENC_FILE = os.path.join(_PROJECT_ROOT, ".env.enc")
_MASTER_KEY_VAR = "GRADING_MASTER_KEY"

# 관리 대상 키 목록 (set 명령어 안내용)
KNOWN_KEYS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
]


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────
def _require_cryptography():
    try:
        from cryptography.fernet import Fernet
        return Fernet
    except ImportError:
        print("[오류] cryptography 패키지 필요: pip install cryptography")
        sys.exit(1)


def _get_master_key() -> bytes:
    """GRADING_MASTER_KEY 환경변수에서 읽거나 터미널 입력 받기"""
    key = os.environ.get(_MASTER_KEY_VAR)
    if key:
        return key.encode()
    print(f"{_MASTER_KEY_VAR} 환경변수가 없습니다.")
    key = getpass.getpass("MASTER_KEY 입력 (입력값 비표시): ").strip()
    if not key:
        print("[오류] MASTER_KEY가 비어있습니다.")
        sys.exit(1)
    return key.encode()


def _load_plain(fernet) -> dict[str, str]:
    """현재 .env.enc를 복호화해 dict 반환"""
    from cryptography.fernet import InvalidToken
    if not os.path.exists(_ENC_FILE):
        return {}
    try:
        encrypted = open(_ENC_FILE, "rb").read()
        plaintext = fernet.decrypt(encrypted).decode("utf-8")
    except InvalidToken:
        print("[오류] MASTER_KEY가 틀렸거나 .env.enc 파일이 손상되었습니다.")
        sys.exit(1)

    result: dict[str, str] = {}
    for line in plaintext.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _save_plain(fernet, secrets: dict[str, str]) -> None:
    """dict를 암호화해 .env.enc에 저장"""
    lines = ["# 자동 생성 — 직접 편집하지 마세요", ""]
    for k, v in sorted(secrets.items()):
        lines.append(f"{k}={v}")
    plaintext = "\n".join(lines) + "\n"
    encrypted = fernet.encrypt(plaintext.encode("utf-8"))
    with open(_ENC_FILE, "wb") as f:
        f.write(encrypted)
    print(f"  → .env.enc 저장 완료 ({len(secrets)}개 키)")


# ── 명령어 구현 ───────────────────────────────────────────────────────────────
def cmd_init():
    """신규 MASTER_KEY 발급 및 안내"""
    Fernet = _require_cryptography()
    from cryptography.fernet import Fernet as F
    key = F.generate_key().decode()
    print()
    print("=" * 60)
    print("  신규 MASTER_KEY 발급 완료")
    print("=" * 60)
    print(f"\n  {key}\n")
    print("─" * 60)
    print("[로컬] 아래 명령어를 ~/.zshrc 또는 ~/.bashrc에 추가하세요:")
    print(f"\n  export {_MASTER_KEY_VAR}={key}\n")
    print("[클라우드] 배포 플랫폼의 환경변수 설정에 아래 키-값을 추가하세요:")
    print(f"\n  Key:   {_MASTER_KEY_VAR}")
    print(f"  Value: {key}\n")
    print("─" * 60)
    print("[주의] 이 키를 git에 커밋하거나 타인과 공유하지 마세요.")
    print("       키를 분실하면 .env.enc 내용을 복구할 수 없습니다.")
    print("=" * 60)


def cmd_set():
    """API 키 추가/수정 — getpass로 입력값 비표시"""
    Fernet = _require_cryptography()
    master = _get_master_key()
    fernet = Fernet(master)
    secrets = _load_plain(fernet)

    print()
    print("저장할 키 이름을 선택하거나 직접 입력하세요.")
    for i, k in enumerate(KNOWN_KEYS, 1):
        status = "✓ 저장됨" if k in secrets else "  미설정"
        print(f"  {i}. {k}  [{status}]")
    print(f"  {len(KNOWN_KEYS)+1}. 직접 입력")
    print()

    choice = input("번호 또는 키 이름: ").strip()
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(KNOWN_KEYS):
            key_name = KNOWN_KEYS[idx]
        elif idx == len(KNOWN_KEYS):
            key_name = input("키 이름 입력: ").strip()
        else:
            print("[오류] 잘못된 번호")
            sys.exit(1)
    except ValueError:
        key_name = choice  # 직접 이름 입력

    if not key_name:
        print("[오류] 키 이름이 비어있습니다.")
        sys.exit(1)

    # getpass로 값 입력 (터미널에 표시 안 됨)
    value = getpass.getpass(f"{key_name} 값 입력 (입력값 비표시): ").strip()
    if not value:
        print("[오류] 값이 비어있습니다.")
        sys.exit(1)

    # 확인용 재입력
    confirm = getpass.getpass(f"{key_name} 값 재입력 (확인): ").strip()
    if value != confirm:
        print("[오류] 입력값이 일치하지 않습니다.")
        sys.exit(1)

    secrets[key_name] = value
    _save_plain(fernet, secrets)
    print(f"  '{key_name}' 저장 완료 ✓")


def cmd_list():
    """저장된 키 이름 목록 출력 (값은 마스킹)"""
    Fernet = _require_cryptography()
    master = _get_master_key()
    fernet = Fernet(master)
    secrets = _load_plain(fernet)

    if not secrets:
        print("  저장된 시크릿이 없습니다.")
        return

    print()
    print(f"  저장된 시크릿 ({len(secrets)}개):")
    print("  " + "─" * 40)
    for k, v in sorted(secrets.items()):
        masked = v[:4] + "*" * (len(v) - 8) + v[-4:] if len(v) > 10 else "****"
        print(f"  {k:<30} {masked}")
    print()


def cmd_delete():
    """특정 키 삭제"""
    Fernet = _require_cryptography()
    master = _get_master_key()
    fernet = Fernet(master)
    secrets = _load_plain(fernet)

    if not secrets:
        print("  저장된 시크릿이 없습니다.")
        return

    print()
    keys = sorted(secrets.keys())
    for i, k in enumerate(keys, 1):
        print(f"  {i}. {k}")
    print()

    choice = input("삭제할 번호 또는 키 이름: ").strip()
    try:
        idx = int(choice) - 1
        key_name = keys[idx]
    except (ValueError, IndexError):
        key_name = choice

    if key_name not in secrets:
        print(f"  [오류] '{key_name}' 키가 없습니다.")
        sys.exit(1)

    confirm = input(f"  '{key_name}'을 삭제합니까? (y/N): ").strip().lower()
    if confirm != "y":
        print("  취소")
        return

    del secrets[key_name]
    _save_plain(fernet, secrets)
    print(f"  '{key_name}' 삭제 완료 ✓")


def cmd_export():
    """클라우드 설정용 export 출력 (값 마스킹, 직접 참고용)"""
    Fernet = _require_cryptography()
    master = _get_master_key()
    fernet = Fernet(master)
    secrets = _load_plain(fernet)

    if not secrets:
        print("  저장된 시크릿이 없습니다.")
        return

    print()
    print("  클라우드 환경변수 설정 목록 (값은 마스킹 — 실제 값은 .env.enc에 암호화됨):")
    print("  " + "─" * 50)
    print(f"  {_MASTER_KEY_VAR}=<발급된 MASTER_KEY>  ← 반드시 설정 필요")
    for k in sorted(secrets.keys()):
        print(f"  {k}=****  (암호화된 .env.enc에서 자동 로드)")
    print()


# ── 진입점 ────────────────────────────────────────────────────────────────────
COMMANDS = {
    "init":   cmd_init,
    "set":    cmd_set,
    "list":   cmd_list,
    "delete": cmd_delete,
    "export": cmd_export,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("사용 가능한 명령어:", ", ".join(COMMANDS))
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
