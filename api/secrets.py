"""
시크릿 로더: .env.enc 파일을 GRADING_MASTER_KEY로 복호화 → os.environ 주입

사용처: api/server.py startup 시 load_secrets() 한 번 호출
환경변수 우선순위: 이미 설정된 os.environ > .env.enc 내용
"""
from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENC_FILE = os.path.join(_PROJECT_ROOT, ".env.enc")
_MASTER_KEY_VAR = "GRADING_MASTER_KEY"


def load_secrets() -> None:
    """
    .env.enc 파일을 복호화해 os.environ에 주입한다.
    - GRADING_MASTER_KEY 환경변수가 없으면 경고 후 스킵
    - .env.enc 파일이 없으면 스킵 (환경변수 직접 주입 허용)
    - 이미 설정된 환경변수는 덮어쓰지 않음
    """
    master_key = os.environ.get(_MASTER_KEY_VAR)

    if not master_key:
        logger.warning(
            "%s 환경변수 없음 — .env.enc 로드 스킵 (os.environ 직접 설정 시 무시 가능)",
            _MASTER_KEY_VAR,
        )
        return

    if not os.path.exists(_ENC_FILE):
        logger.info(".env.enc 파일 없음 — os.environ 직접 설정 모드로 동작")
        return

    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:
        logger.error("cryptography 패키지 미설치: pip install cryptography")
        sys.exit(1)

    try:
        fernet = Fernet(master_key.encode())
        encrypted = open(_ENC_FILE, "rb").read()
        plaintext = fernet.decrypt(encrypted).decode("utf-8")
    except InvalidToken:
        logger.error("GRADING_MASTER_KEY가 틀렸거나 .env.enc 파일이 손상되었습니다.")
        sys.exit(1)
    except Exception as e:
        logger.error(".env.enc 복호화 실패: %s", e)
        sys.exit(1)

    injected = 0
    for line in plaintext.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:   # 이미 설정된 값 보호
            os.environ[key] = value
            injected += 1

    logger.info(".env.enc 복호화 완료 — %d개 키 주입", injected)
