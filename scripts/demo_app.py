"""데모용 Streamlit 실행 스크립트 — 모델·서버 없이 UI를 그대로 띄운다.

    streamlit run scripts/demo_app.py

app/main.py의 화면 코드를 그대로 쓰되, 무거운 구성요소만 scripts/demo.py의
대역(인메모리 Qdrant · 해싱 임베더 · 발췌형 스텁 LLM)으로 바꿔 끼운다.
실제 운영 실행은 `streamlit run app/main.py`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("EMBED_DIM", "256")
os.environ.setdefault("LOG_DIR", str(ROOT / "logs"))

import streamlit as st  # noqa: E402

import vectordb.store as store_module  # noqa: E402
from scripts.demo import SAMPLE, install_demo_doubles  # noqa: E402


@st.cache_resource(show_spinner="샘플 규정을 색인하는 중…")
def _demo_client():
    """인메모리 Qdrant에 샘플 규정을 한 번만 색인하고 재실행 간 재사용한다."""
    from qdrant_client import QdrantClient

    from pipeline.build_index import build_chunks, index_chunks
    from vectordb.setup import create_collection

    client = QdrantClient(":memory:")
    create_collection(client)
    index_chunks(build_chunks(SAMPLE), client=client)
    return client


install_demo_doubles()
client = _demo_client()
store_module.get_client = lambda: client  # 파이프라인이 인메모리 클라이언트를 쓰도록

st.warning(
    "**데모 모드** — 임베딩·리랭커·LLM이 가벼운 대역으로 대체돼 있습니다. "
    "화면과 배선을 확인하기 위한 것이며 검색·답변 품질은 실제 구성과 다릅니다.",
    icon="⚠️",
)

from app.main import main  # noqa: E402

main()
