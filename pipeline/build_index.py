"""색인 파이프라인 (명세 2.7).

원문 → 파싱 → 조항 청킹 → 임베딩 → Qdrant upsert 를 한 번에 돌린다.

실행:
    python -m pipeline.build_index                # DATA_DIR 전체 색인
    python -m pipeline.build_index --recreate     # 컬렉션을 비우고 처음부터
    python -m pipeline.build_index --file 인사규정.hwp
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from chunking.article_splitter import chunk_document
from config import get_settings
from loaders.hwp_loader import DocumentLoadError, iter_documents, load_document
from metadata.filename_parser import parse_filename_metadata

logger = logging.getLogger(__name__)


def build_chunks(filepath: str | Path) -> list[dict]:
    """파일 하나를 색인 직전 형태의 조항 청크 리스트로 만든다."""
    path = Path(filepath)
    doc = load_document(path)
    meta = parse_filename_metadata(path.name)
    meta["source_file"] = str(path)

    if not meta["effective_date"]:
        # 파일명 규칙에 맞지 않는 경우에만 처리일로 보정한다. 색인은 막지 않되 로그로 남긴다.
        meta["effective_date"] = date.today().isoformat()
        logger.warning("파일명에서 시행일자를 못 읽었습니다 (처리일로 보정): %s", path.name)

    chunks = chunk_document(doc.text, meta)
    if not chunks:
        logger.warning("조항을 하나도 찾지 못했습니다 — 청킹 규칙 확인 필요: %s", path.name)
    return chunks


def index_chunks(chunks: list[dict], client=None) -> int:
    """청크를 임베딩해 Qdrant에 저장한다."""
    from embedding.embedder import get_embedder
    from vectordb.store import upsert_articles

    if not chunks:
        return 0
    result = get_embedder().encode([c["text"] for c in chunks])
    return upsert_articles(chunks, result.dense, result.sparse, client=client)


def index_file(filepath: str | Path, client=None) -> int:
    chunks = build_chunks(filepath)
    n = index_chunks(chunks, client=client)
    logger.info("%s: 조항 %d개 색인", Path(filepath).name, n)
    return n


def index_directory(directory: str | Path | None = None, client=None) -> dict[str, int]:
    s = get_settings()
    directory = Path(directory or s.data_dir)
    results: dict[str, int] = {}
    files = list(iter_documents(directory))
    if not files:
        logger.warning("색인할 문서가 없습니다: %s", directory)

    for path in files:
        try:
            results[path.name] = index_file(path, client=client)
        except DocumentLoadError as exc:
            logger.error("파싱 실패로 건너뜁니다: %s", exc)
            results[path.name] = 0
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="사규·법령 원문을 색인한다")
    parser.add_argument("--dir", default=None, help="원문 디렉터리 (기본: DATA_DIR)")
    parser.add_argument("--file", default=None, help="파일 하나만 색인")
    parser.add_argument("--recreate", action="store_true", help="컬렉션을 지우고 다시 만든다")
    args = parser.parse_args()

    from vectordb.setup import create_collection, get_client
    from vectordb.store import count

    client = get_client()
    create_collection(client, recreate=args.recreate)

    if args.file:
        index_file(args.file, client=client)
    else:
        results = index_directory(args.dir, client=client)
        total = sum(results.values())
        for name, n in results.items():
            logger.info("  %-40s %4d 조항", name, n)
        logger.info("문서 %d개 / 조항 %d개 색인", len(results), total)

    logger.info("컬렉션 총 조항 수: %d", count(client))


if __name__ == "__main__":
    main()
