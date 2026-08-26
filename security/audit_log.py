"""감사 로그 (명세 6.2 — 데이터 계층).

"AI가 어떤 근거로 어떤 답을 줬는지"를 그대로 추적 자료로 남긴다.
다만 감사로그 자체가 개인정보 처리 행위이므로 세 가지를 구조에 넣어둔다.

  1. user_id는 실명 대신 단방향 해시(가명처리)로만 남긴다.
  2. question·answer는 저장 전에 PII 마스킹을 거친다.
  3. 보존기간(RETENTION_DAYS)이 지난 로그는 지체 없이 파기한다.

prompt_version·model_version 필드는 4.5의 회고적 비교("프롬프트를 바꾸기 전/후
신뢰도 평균이 어떻게 달라졌는가")를 로그만으로 되짚기 위한 것이다.

로그 파일 자체도 개인정보이므로, RBAC과 별개로 logs/ 디렉터리 접근권한을
관리자로 제한해야 한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from config import get_settings
from security.pii_mask import mask_pii

logger = logging.getLogger(__name__)


def _salt() -> str:
    s = get_settings().audit_salt
    if s == "change-me-in-production":
        logger.warning("AUDIT_SALT가 기본값입니다. 운영 전에 반드시 임의값으로 교체하세요.")
    return s


def pseudonymize(user_id: str) -> str:
    """로그에는 실명 대신 단방향 해시만 남긴다.

    감사 등 실명 복원이 꼭 필요한 경우에는 사번-해시 매핑 테이블을 별도로,
    감사로그보다 더 엄격한 접근권한으로 보관한다.
    """
    return hashlib.sha256(f"{user_id}-{_salt()}".encode("utf-8")).hexdigest()[:16]


def _append_jsonl(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=False를 넣어야 로그 파일에서도 한글이 깨지지 않는다
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    try:
        os.chmod(path, 0o600)  # 소유자만 읽기 — 로그도 개인정보다
    except OSError:
        pass


def log_qa_event(
    user_id: str,
    question: str,
    answer: str,
    sources: list[str],
    confidence: str,
    *,
    message_id: str | None = None,
    log_path: str | Path | None = None,
) -> dict:
    s = get_settings()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "message_id": message_id,
        "user_id": pseudonymize(user_id),
        "question": mask_pii(question),
        "answer": mask_pii(answer),
        "sources": sources,
        "confidence": confidence,
        "prompt_version": s.prompt_version,
        "model_version": s.llm_model,
    }
    _append_jsonl(Path(log_path or s.audit_log_path), entry)
    return entry


def log_feedback(message_id: str, verdict: str, *, log_path: str | Path | None = None) -> dict:
    """사용자 피드백(👍/👎). 골든셋 자동 확장(4.5)의 입력이 된다."""
    s = get_settings()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "message_id": message_id,
        "verdict": verdict,  # "positive" | "negative"
    }
    _append_jsonl(Path(log_path or s.feedback_log_path), entry)
    return entry


def read_log(log_path: str | Path) -> list[dict]:
    """깨진 줄은 건너뛰고 읽는다."""
    path = Path(log_path)
    if not path.exists():
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("로그 %s:%d 줄을 건너뜁니다", path, line_no)
    return entries


def purge_old_logs(log_path: str | Path | None = None, retention_days: int | None = None) -> int:
    """보존기간이 지난 로그를 지체 없이 파기한다. cron으로 매일 실행.

    파기한 줄 수를 돌려준다.
    """
    s = get_settings()
    path = Path(log_path or s.audit_log_path)
    days = s.retention_days if retention_days is None else retention_days
    if not path.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=days)
    kept, purged = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                ts = datetime.fromisoformat(json.loads(line)["timestamp"])
            except (json.JSONDecodeError, KeyError, ValueError):
                purged += 1  # 판단 불가한 줄은 남기지 않는다
                continue
            if ts >= cutoff:
                kept.append(line if line.endswith("\n") else line + "\n")
            else:
                purged += 1

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(kept)
    logger.info("%s: %d줄 파기, %d줄 유지", path, purged, len(kept))
    return purged


def main() -> None:
    """python -m security.audit_log — 보존기간 지난 로그 파기 (cron 등록용)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    s = get_settings()
    for path in (s.audit_log_path, s.feedback_log_path):
        purge_old_logs(path)


if __name__ == "__main__":
    main()
