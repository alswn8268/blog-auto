"""조항 개정 자동 감지 및 재색인 (명세 4.4).

사규 개정 공지가 날 때마다 사람이 수동으로 다시 색인하는 대신,
파일 변경을 감지해 **바뀐 조항만** 자동으로 갱신한다.

설계 포인트 네 가지
  1. 파일 전체가 아니라 조항 단위로 변경 여부를 비교한다. 조항이 100개여도
     실제로 바뀐 2~3개만 재임베딩하므로 계산 비용이 실제로 줄어든다.
  2. 기존 조항을 삭제하지 않고 superseded_by로 표시만 하므로,
     개정 이력 추적(4.2)과 데이터가 자연스럽게 이어진다.
  3. effective_date가 처리 시점이 아니라 파일명에서 뽑은 실제 시행일자다(2.1).
  4. 트리거는 상황에 맞게 고른다.
       cron 스케줄        구현이 가장 쉬움. 1개월 프로토타입은 이 정도로 충분
       watchdog 감시      개정 반영을 거의 실시간으로 하고 싶을 때
       그룹웨어 webhook   6.1의 그룹웨어 연동과 자연스럽게 결합

실행: python -m features.auto_reindex            (cron: 0 3 * * *)
      python -m features.auto_reindex --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import date
from pathlib import Path

from chunking.article_splitter import normalize_article_no
from config import get_settings
from features.revision_diff import is_changed
from loaders.hwp_loader import SUPPORTED_SUFFIXES
from metadata.filename_parser import parse_filename_metadata
from pipeline.build_index import build_chunks

logger = logging.getLogger(__name__)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_hash_store(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("해시 저장소가 손상되어 새로 만듭니다: %s", path)
        return {}


def save_hash_store(path: Path, store: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def detect_changed_files(watch_dir: Path, hash_store: dict[str, str]) -> list[Path]:
    """이전에 기록해둔 해시와 비교해 변경된 파일만 골라낸다.

    hash_store는 이 함수 안에서 갱신된다 — 호출부가 재색인에 성공한 뒤 저장하면 된다.
    """
    changed = []
    for f in sorted(Path(watch_dir).rglob("*")):
        if not f.is_file() or f.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        h = file_hash(f)
        if hash_store.get(str(f)) != h:
            changed.append(f)
            hash_store[str(f)] = h
    return changed


def diff_chunks(old_chunks: list[dict], new_chunks: list[dict]) -> list[tuple[dict | None, dict]]:
    """기존 조항과 비교해 '진짜 바뀐' 조항만 추린다 (4.2의 비교 로직 재사용).

    조 번호 표기가 흔들려도(제 15 조 / 제15조) 같은 조항으로 매칭되도록 정규화 키를 쓴다.
    """
    old_by_no = {normalize_article_no(o.get("article_no", "")): o for o in old_chunks}
    changed: list[tuple[dict | None, dict]] = []
    for new in new_chunks:
        old = old_by_no.get(normalize_article_no(new.get("article_no", "")))
        if old is None or is_changed(old.get("text", ""), new.get("text", "")):
            changed.append((old, new))
    return changed


def reindex_changed_file(filepath: Path, qdrant_client, embed_fn=None, *, dry_run: bool = False) -> int:
    """파일 하나를 재색인한다. 실제로 갱신된 조항 수를 돌려준다."""
    from vectordb.store import fetch_current_articles, mark_superseded, upsert_articles

    filepath = Path(filepath)

    # 0. 파일명 규칙에서 실제 시행일자 추출 (2.1의 parse_filename_metadata 재사용)
    meta = parse_filename_metadata(filepath.name)
    effective_date = meta["effective_date"] or date.today().isoformat()
    doc_title = meta["doc_title"]

    # 1. 재파싱 + 재청킹
    new_chunks = build_chunks(filepath)
    if not new_chunks:
        return 0

    # 2. 기존 조항과 비교해 "진짜 바뀐" 조항만 추림
    old_chunks = fetch_current_articles(qdrant_client, doc_title=doc_title)
    changed = diff_chunks(old_chunks, new_chunks)
    if not changed:
        logger.info("%s: 내용이 바뀐 조항 없음", filepath.name)
        return 0

    logger.info("%s: 조항 %d개 변경 (시행 %s)", filepath.name, len(changed), effective_date)
    if dry_run:
        for old, new in changed:
            logger.info("  %s %s", new["article_no"], "신설" if old is None else "개정")
        return len(changed)

    # 3. 변경분만 재임베딩 + upsert, 기존본은 superseded 처리(이력 보존)
    if embed_fn is None:
        from embedding.embedder import get_embedder

        embed_fn = get_embedder().encode

    targets = [new for _, new in changed]
    vectors = embed_fn([c["text"] for c in targets])
    upsert_articles(targets, vectors.dense, vectors.sparse, client=qdrant_client)

    for old, new in changed:
        if old:
            mark_superseded(
                qdrant_client, old["id"], superseded_by=new["id"], until=effective_date
            )
    return len(changed)


def run(watch_dir: str | Path | None = None, *, dry_run: bool = False) -> dict[str, int]:
    s = get_settings()
    watch_dir = Path(watch_dir or s.data_dir)
    store_path = s.hash_store_path
    hash_store = load_hash_store(store_path)

    changed_files = detect_changed_files(watch_dir, hash_store)
    if not changed_files:
        logger.info("변경된 파일이 없습니다: %s", watch_dir)
        return {}

    from vectordb.setup import get_client

    client = get_client()
    results: dict[str, int] = {}
    for f in changed_files:
        try:
            results[f.name] = reindex_changed_file(f, client, dry_run=dry_run)
        except Exception:
            logger.exception("재색인 실패: %s", f.name)
            hash_store.pop(str(f), None)  # 다음 실행에서 다시 시도하도록 해시를 되돌린다

    if not dry_run:
        save_hash_store(store_path, hash_store)
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="변경된 사규 파일의 바뀐 조항만 재색인한다")
    parser.add_argument("--dir", default=None, help="감시 디렉터리 (기본: DATA_DIR)")
    parser.add_argument("--dry-run", action="store_true", help="무엇이 바뀌는지만 출력")
    args = parser.parse_args()

    results = run(args.dir, dry_run=args.dry_run)
    total = sum(results.values())
    logger.info("파일 %d개 / 조항 %d개 갱신", len(results), total)


if __name__ == "__main__":
    main()
