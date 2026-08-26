"""관리자 화면 — 로그 기반 개선 루프(4.5)를 눈으로 확인하는 페이지.

  · 저신뢰 질문 클러스터 → "이런 질문이 반복되는데 관련 문서가 부족합니다"
  · 버전별 신뢰도 → 프롬프트 변경 전/후 회고적 비교
  · 피드백 큐 → 골든셋 추가 후보 / 검토 대상

주의: 이 화면은 질문 로그를 그대로 다루므로, 배포 시 관리자만 접근하도록
리버스 프록시 단에서 경로를 제한해야 한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from config import get_settings  # noqa: E402
from improvement.gap_analysis import (  # noqa: E402
    collect_feedback_candidates,
    compare_versions,
    report_document_gaps,
)
from security.audit_log import purge_old_logs, read_log  # noqa: E402

st.set_page_config(page_title="관리자 · 사규 Q&A", page_icon="🛠️", layout="wide")
st.title("🛠️ 관리자")

s = get_settings()
entries = read_log(s.audit_log_path)

col1, col2, col3 = st.columns(3)
col1.metric("누적 질문", len(entries))
col2.metric("저신뢰(하) 비율",
            f"{sum(1 for e in entries if e.get('confidence') == '하') / len(entries):.0%}" if entries else "-")
col3.metric("보존기간", f"{s.retention_days}일")

tab_gap, tab_version, tab_feedback, tab_privacy = st.tabs(
    ["문서 공백", "버전별 신뢰도", "피드백 큐", "로그 관리"]
)

with tab_gap:
    st.subheader("저신뢰 질문 클러스터")
    st.caption("답을 제대로 못 준 질문을 주제별로 묶은 것입니다. 다음에 색인할 문서의 우선순위가 됩니다.")
    gaps = report_document_gaps()
    if not gaps:
        st.info("아직 저신뢰 질문이 없습니다.")
    for i, g in enumerate(gaps, 1):
        with st.expander(f"{i}. {g['size']}건 — {g['sample'][0][:40]}"):
            for q in g["questions"]:
                st.write("・", q)

with tab_version:
    st.subheader("prompt_version · model_version별 평균 신뢰도")
    rows = compare_versions()
    if rows:
        st.dataframe(rows, use_container_width=True)
    else:
        st.info("비교할 로그가 없습니다.")

with tab_feedback:
    fb = collect_feedback_candidates()
    st.subheader(f"👍 골든셋 추가 후보 ({len(fb['golden_candidates'])})")
    st.caption("사람이 한 번 검수한 뒤 골든셋에 넣습니다. 자동 승격은 하지 않습니다.")
    st.dataframe(fb["golden_candidates"], use_container_width=True) if fb["golden_candidates"] else st.info("없음")

    st.subheader(f"👎 검토 큐 ({len(fb['review_queue'])})")
    st.caption("프롬프트·청킹 개선의 재료로 씁니다.")
    st.dataframe(fb["review_queue"], use_container_width=True) if fb["review_queue"] else st.info("없음")

with tab_privacy:
    st.subheader("로그 파기")
    st.caption(
        "감사로그는 그 자체가 개인정보 처리 행위입니다. 실명은 단방향 해시로만, "
        "질문·답변은 PII 마스킹 후 저장되며, 보존기간이 지나면 지체 없이 파기합니다."
    )
    st.code(f"{s.audit_log_path}\n{s.feedback_log_path}", language="text")
    if st.button(f"보존기간({s.retention_days}일) 지난 로그 파기"):
        purged = purge_old_logs(s.audit_log_path) + purge_old_logs(s.feedback_log_path)
        st.success(f"{purged}줄 파기했습니다.")
