"""Qdrant 컬렉션 생성 (명세 2.4).

dense(의미) + sparse(키워드) 두 벡터를 한 컬렉션에 함께 두어
아키텍처 그림의 '하이브리드 검색'을 별도 인덱스 없이 구현한다.

payload 필드는 처음부터 잡아둔다. 조항충돌탐지(4.1)·개정이력추적(4.2)·
자동 재색인(4.4)·RBAC(6.2)이 모두 이 필드들 위에서 돌아간다.

    doc_type        "사규" | "법령" | "판례" — 도메인별 라우팅·RBAC 필터
    doc_title       문서명 (예: "인사규정")
    article_no      조 번호 (예: "제15조")
    article_title   조 제목 (예: "전보")
    parent_section  소속 장/절
    effective_date  시행일자 — 개정이력추적의 핵심 필드
    superseded_by   최신본 여부/후속 버전 참조
    source_file     원본 파일 경로

실행: python -m vectordb.setup [--recreate]
"""

from __future__ import annotations

import argparse
import logging

from config import get_settings

logger = logging.getLogger(__name__)

DENSE = "dense"
SPARSE = "sparse"

# 필터 검색이 잦은 필드는 payload 인덱스를 걸어둔다
INDEXED_PAYLOAD_FIELDS = ("doc_type", "doc_title", "article_no", "effective_date", "superseded_by")


def get_client():
    """Qdrant 클라이언트. 지연 임포트라 qdrant-client 없이도 다른 모듈은 임포트된다."""
    from qdrant_client import QdrantClient

    return QdrantClient(url=get_settings().qdrant_url)


def create_collection(client=None, *, recreate: bool = False) -> None:
    from qdrant_client import models

    s = get_settings()
    client = client or get_client()

    exists = client.collection_exists(s.collection)
    if exists and not recreate:
        logger.info("컬렉션이 이미 있습니다: %s", s.collection)
        return
    if exists and recreate:
        logger.warning("컬렉션을 삭제하고 다시 만듭니다: %s", s.collection)
        client.delete_collection(s.collection)

    client.create_collection(
        collection_name=s.collection,
        vectors_config={
            DENSE: models.VectorParams(size=s.dense_dim, distance=models.Distance.COSINE),
        },
        sparse_vectors_config={
            SPARSE: models.SparseVectorParams(index=models.SparseIndexParams()),
        },
    )

    for field in INDEXED_PAYLOAD_FIELDS:
        client.create_payload_index(
            collection_name=s.collection,
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    logger.info("컬렉션 생성 완료: %s", s.collection)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Qdrant 컬렉션을 만든다")
    parser.add_argument("--recreate", action="store_true", help="기존 컬렉션을 지우고 다시 만든다")
    args = parser.parse_args()
    create_collection(recreate=args.recreate)


if __name__ == "__main__":
    main()
