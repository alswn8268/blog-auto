"""Qdrant 색인·검색 래퍼.

- upsert_articles: 조항 청크를 dense+sparse 벡터와 함께 저장
- hybrid_search:   dense/sparse 두 갈래를 RRF로 융합해 후보를 뽑음 (아키텍처의 '하이브리드 검색')
- fetch_current_articles / mark_superseded: 4.4 자동 재색인이 쓰는 이력 관리
"""

from __future__ import annotations

import logging
from typing import Any

from config import get_settings
from vectordb.setup import DENSE, SPARSE, get_client

logger = logging.getLogger(__name__)

PAYLOAD_FIELDS = (
    "doc_type",
    "doc_title",
    "article_no",
    "article_title",
    "parent_section",
    "effective_date",
    "revision_type",
    "superseded_by",
    "source_file",
    "is_addenda",
    "text",
)


def to_sparse_vector(weights: dict[str, float]):
    """BGE-M3의 lexical_weights({토큰id: 가중치})를 Qdrant SparseVector로."""
    from qdrant_client import models

    indices, values = [], []
    for k, v in weights.items():
        try:
            indices.append(int(k))
        except (TypeError, ValueError):
            continue
        values.append(float(v))
    return models.SparseVector(indices=indices, values=values)


def _payload(chunk: dict) -> dict[str, Any]:
    return {k: chunk.get(k) for k in PAYLOAD_FIELDS}


def upsert_articles(
    chunks: list[dict],
    dense_vecs: list[list[float]],
    sparse_vecs: list[dict[str, float]],
    client=None,
    *,
    batch_size: int = 64,
) -> int:
    """조항 청크를 벡터와 함께 저장한다. 같은 id면 덮어쓴다."""
    from qdrant_client import models

    if not chunks:
        return 0
    if not (len(chunks) == len(dense_vecs) == len(sparse_vecs)):
        raise ValueError("청크 수와 벡터 수가 맞지 않습니다")

    s = get_settings()
    client = client or get_client()

    points = [
        models.PointStruct(
            id=chunk["id"],
            vector={DENSE: dense, SPARSE: to_sparse_vector(sparse)},
            payload=_payload(chunk),
        )
        for chunk, dense, sparse in zip(chunks, dense_vecs, sparse_vecs)
    ]

    for i in range(0, len(points), batch_size):
        client.upsert(collection_name=s.collection, points=points[i : i + batch_size], wait=True)
    logger.info("%d개 조항 색인 완료", len(points))
    return len(points)


def _hit_to_chunk(hit) -> dict:
    payload = dict(hit.payload or {})
    payload["id"] = hit.id
    payload["search_score"] = float(getattr(hit, "score", 0.0) or 0.0)
    return payload


def combine_filters(*filters):
    """여러 Qdrant 필터를 AND로 합친다 (RBAC 필터 + 라우팅 필터 등).

    None은 무시한다. 합칠 것이 없으면 None을 돌려준다.
    should 절을 가진 필터가 둘 이상이면 서로의 OR가 섞여 의미가 무너지므로,
    그런 필터는 통째로 must 안에 중첩시켜 각자의 should를 보존한다.
    """
    from qdrant_client import models

    present = [f for f in filters if f is not None]
    if not present:
        return None
    if len(present) == 1:
        return present[0]

    must, must_not = [], []
    for f in present:
        if getattr(f, "should", None) or getattr(f, "min_should", None):
            must.append(models.Filter(should=f.should, min_should=getattr(f, "min_should", None)))
            if f.must:
                must.extend(f.must)
            if f.must_not:
                must_not.extend(f.must_not)
            continue
        if f.must:
            must.extend(f.must)
        if f.must_not:
            must_not.extend(f.must_not)
    return models.Filter(must=must or None, must_not=must_not or None)


def _fusion_query():
    """설정된 융합 방식. rrf는 순위 기반, dbsf는 점수 분포 기반."""
    from qdrant_client import models

    name = get_settings().fusion
    if name == "dbsf":
        return models.FusionQuery(fusion=models.Fusion.DBSF)
    if name != "rrf":
        logger.warning("알 수 없는 FUSION=%s — rrf로 대체합니다", name)
    return models.FusionQuery(fusion=models.Fusion.RRF)


def hybrid_search(
    query_dense: list[float],
    query_sparse: dict[str, float],
    limit: int | None = None,
    query_filter=None,
    client=None,
    extra_queries: list[tuple[list[float], dict[str, float]]] | None = None,
) -> list[dict]:
    """dense·sparse 후보를 각각 뽑아 융합한다.

    extra_queries를 주면(Multi-Query) 변형 질문마다 dense/sparse 갈래를 더 만들어
    한 번의 호출로 전부 융합한다. 질문 변형이 각자 다른 조항을 물어와도
    순위 융합이 이를 하나의 목록으로 합쳐준다.

    query_filter로 RBAC 필터(6.2)나 도메인 라우팅 필터를 그대로 끼워 넣을 수 있다.
    """
    from qdrant_client import models

    s = get_settings()
    client = client or get_client()
    limit = limit or s.retrieve_top_k
    prefetch_limit = max(limit * max(s.prefetch_multiplier, 1), limit)

    pairs = [(query_dense, query_sparse), *(extra_queries or [])]
    prefetch = []
    for dense, sparse in pairs:
        prefetch.append(
            models.Prefetch(query=dense, using=DENSE, limit=prefetch_limit, filter=query_filter)
        )
        if sparse:
            prefetch.append(
                models.Prefetch(
                    query=to_sparse_vector(sparse),
                    using=SPARSE,
                    limit=prefetch_limit,
                    filter=query_filter,
                )
            )

    response = client.query_points(
        collection_name=s.collection,
        prefetch=prefetch,
        query=_fusion_query(),
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
    )
    return [_hit_to_chunk(p) for p in response.points]


def fetch_current_articles(client, doc_title: str) -> list[dict]:
    """해당 문서에서 아직 superseded 되지 않은(=현행) 조항 전체를 가져온다."""
    from qdrant_client import models

    s = get_settings()
    flt = models.Filter(
        must=[models.FieldCondition(key="doc_title", match=models.MatchValue(value=doc_title))],
        must_not=[models.IsNullCondition(is_null=models.PayloadField(key="superseded_by"))],
    )

    results: list[dict] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=s.collection,
            scroll_filter=flt,
            limit=256,
            offset=offset,
            with_payload=True,
        )
        for p in points:
            payload = dict(p.payload or {})
            payload["id"] = p.id
            results.append(payload)
        if offset is None:
            break
    return results


def fetch_all_articles(client, doc_title: str | None = None) -> list[dict]:
    """(옵션) 문서 전체 조항. 조항 충돌 탐지(4.1) 배치에서 쓴다."""
    from qdrant_client import models

    s = get_settings()
    flt = None
    if doc_title:
        flt = models.Filter(
            must=[models.FieldCondition(key="doc_title", match=models.MatchValue(value=doc_title))]
        )

    results: list[dict] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=s.collection,
            scroll_filter=flt,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=[DENSE],
        )
        for p in points:
            payload = dict(p.payload or {})
            payload["id"] = p.id
            vectors = p.vector if isinstance(p.vector, dict) else {}
            payload["embedding"] = vectors.get(DENSE)
            results.append(payload)
        if offset is None:
            break
    return results


def mark_superseded(client, point_id: str, superseded_by: str, until: str | None = None) -> None:
    """기존 조항을 지우지 않고 '대체됨'으로 표시만 한다 — 개정 이력(4.2)이 보존된다."""
    s = get_settings()
    payload = {"superseded_by": superseded_by}
    if until:
        payload["superseded_at"] = until
    client.set_payload(collection_name=s.collection, payload=payload, points=[point_id], wait=True)


def count(client=None) -> int:
    s = get_settings()
    client = client or get_client()
    return client.count(collection_name=s.collection, exact=True).count
