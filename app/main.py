"""Streamlit 프론트엔드 (명세 2.8).

화면에서 지키는 두 가지:
  - 답변에는 항상 근거 조항을 함께 보여준다 (펼쳐보기)
  - 신뢰도 배지(4.3)를 답변 옆에 붙여, 낮은 답을 그대로 신뢰하지 않게 한다

실행: streamlit run app/main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# `streamlit run app/main.py`로 실행해도 프로젝트 루트를 임포트 경로에 넣는다
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from config import get_settings  # noqa: E402
from features.revision_diff import diff_html  # noqa: E402
from pipeline.query import answer_question  # noqa: E402
from security.audit_log import log_feedback  # noqa: E402

BADGE = {"상": ("🟢", "근거가 뚜렷합니다"),
         "중": ("🟡", "근거를 직접 확인해 보세요"),
         "하": ("🔴", "답변을 그대로 신뢰하지 마세요")}

st.set_page_config(page_title="사규·법령 Q&A", page_icon="📘", layout="wide")


def render_confidence(confidence: str) -> None:
    icon, note = BADGE.get(confidence, ("⚪", ""))
    st.caption(f"{icon} 신뢰도 **{confidence}** — {note}")


def render_sources(contexts: list[dict]) -> None:
    if not contexts:
        st.caption("근거로 삼은 조항이 없습니다.")
        return
    with st.expander(f"근거 조항 보기 ({len(contexts)}건)"):
        for c in contexts:
            title = f" ({c['article_title']})" if c.get("article_title") else ""
            header = f"**{c.get('doc_title', '')} {c.get('article_no', '')}**{title}"
            meta = []
            if c.get("parent_section"):
                meta.append(c["parent_section"])
            if c.get("effective_date"):
                meta.append(f"시행 {c['effective_date']}")
            if c.get("rerank_score") is not None:
                meta.append(f"관련도 {c['rerank_score']:.2f}")
            st.markdown(header + (f"  \n<small>{' · '.join(meta)}</small>" if meta else ""),
                        unsafe_allow_html=True)
            st.text(c.get("text", ""))

            if c.get("superseded_by"):
                st.warning("이 조항은 이후 개정된 버전이 있습니다.")
            if c.get("previous_text"):
                st.markdown("개정 전후 비교")
                st.markdown(diff_html(c["previous_text"], c.get("text", "")))
            st.divider()


def render_feedback(message_id: str) -> None:
    """👍/👎 — 4.5의 골든셋 자동 확장·검토 큐로 흘러간다."""
    col1, col2, _ = st.columns([1, 1, 10])
    if col1.button("👍", key=f"up_{message_id}", help="도움이 됐어요"):
        log_feedback(message_id, "positive")
        st.toast("피드백 감사합니다.")
    if col2.button("👎", key=f"down_{message_id}", help="틀렸거나 부족해요"):
        log_feedback(message_id, "negative")
        st.toast("검토 큐로 보냈습니다.")


def sidebar() -> tuple[str, str]:
    s = get_settings()
    with st.sidebar:
        st.header("설정")
        role = st.selectbox(
            "부서(역할)",
            ["전체직원", "인사팀", "감사실"],
            help="역할에 따라 검색 가능한 문서 범위가 달라집니다 (RBAC).",
        )
        user_id = st.text_input("사번", value="anonymous",
                                help="로그에는 실명이 아닌 단방향 해시로만 남습니다.")
        st.divider()
        st.caption(f"모델: `{s.llm_model}`")
        st.caption(f"컬렉션: `{s.collection}`")
        st.caption(f"프롬프트 버전: `{s.prompt_version}`")
        if st.button("대화 초기화"):
            st.session_state.messages = []
            st.rerun()
    return role, user_id


def main() -> None:
    st.title("📘 사규·법령 Q&A")
    st.caption("사규·법령 원문을 조항 단위로 검색해, 근거 조항을 인용하며 답합니다.")

    role, user_id = sidebar()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                render_confidence(msg.get("confidence", ""))
                render_sources(msg.get("contexts", []))
                render_feedback(msg.get("message_id", ""))

    if question := st.chat_input("궁금한 규정을 물어보세요"):
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("근거 조항을 찾는 중..."):
                result = answer_question(question, user_id=user_id, role=role)

            st.markdown(result.answer)
            if result.error:
                st.error(result.error)
            if not result.blocked:
                render_confidence(result.confidence)
                render_sources(result.contexts)
                render_feedback(result.message_id)

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result.answer,
                "confidence": result.confidence,
                "contexts": result.contexts,
                "message_id": result.message_id,
            }
        )


if __name__ == "__main__":
    main()
