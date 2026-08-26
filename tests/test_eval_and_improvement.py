"""골든셋 변환(3장)과 로그 기반 개선 루프(4.5)."""

import json
from datetime import datetime

import pytest

from eval.build_golden_set import load_existing_qa, merge_colloquial, save_golden_set
from improvement.gap_analysis import (
    collect_feedback_candidates,
    compare_versions,
    find_low_confidence_questions,
    report_document_gaps,
)


# ── 3장 골든셋 ─────────────────────────────────────────────────────────────


def test_운영_QA_JSON을_골든셋_포맷으로_바꾼다(tmp_path):
    src = tmp_path / "qa.json"
    src.write_text(
        json.dumps(
            [
                {"질문": "연차는 며칠인가요?", "답변": "15일입니다", "근거": "복무규정 제20조"},
                {"질문": "", "답변": "빈 질문은 제외"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    golden = load_existing_qa(src)
    assert len(golden) == 1
    assert golden[0]["question"] == "연차는 며칠인가요?"
    assert golden[0]["ground_truth"] == "15일입니다"
    assert golden[0]["reference"] == "복무규정 제20조"


def test_엑셀_대신_CSV로_받아도_동작한다(tmp_path):
    src = tmp_path / "qa.csv"
    src.write_text("질문,답변\n출장비 정산 기한은?,귀임 후 10일 이내\n", encoding="utf-8-sig")
    assert load_existing_qa(src)[0]["ground_truth"] == "귀임 후 10일 이내"


def test_구어체_질문을_섞을_수_있다(tmp_path):
    extra = tmp_path / "colloquial.json"
    extra.write_text(json.dumps([{"question": "연차 며칠 씀?", "ground_truth": "15일"}],
                                ensure_ascii=False), encoding="utf-8")
    merged = merge_colloquial([{"question": "연차는?", "ground_truth": "15일", "origin": "운영Q&A"}], extra)

    assert [item["origin"] for item in merged] == ["운영Q&A", "구어체추가"]


def test_지원하지_않는_형식은_거부한다(tmp_path):
    src = tmp_path / "qa.hwp"
    src.write_bytes(b"x")
    with pytest.raises(ValueError):
        load_existing_qa(src)


def test_골든셋_저장시_한글이_보존된다(tmp_path):
    out = save_golden_set([{"question": "연차는?", "ground_truth": "15일"}], tmp_path / "g.json")
    assert "연차는?" in out.read_text(encoding="utf-8")


# ── 4.5 개선 루프 ──────────────────────────────────────────────────────────


@pytest.fixture
def logs(tmp_path):
    audit = tmp_path / "qa_audit.jsonl"
    feedback = tmp_path / "feedback.jsonl"
    now = datetime.now().isoformat()
    rows = [
        {"timestamp": now, "message_id": "m1", "question": "출장비 정산 기한은?", "answer": "확인되지 않습니다",
         "confidence": "하", "prompt_version": "v1", "model_version": "qwen3:8b", "sources": []},
        {"timestamp": now, "message_id": "m2", "question": "출장비 영수증 필요한가요?", "answer": "확인되지 않습니다",
         "confidence": "하", "prompt_version": "v1", "model_version": "qwen3:8b", "sources": []},
        {"timestamp": now, "message_id": "m3", "question": "연차는 며칠?", "answer": "15일 제20조",
         "confidence": "상", "prompt_version": "v2", "model_version": "qwen3:8b",
         "sources": ["복무규정 제20조"]},
    ]
    audit.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    feedback.write_text(
        "\n".join(
            json.dumps(r, ensure_ascii=False)
            for r in ({"message_id": "m3", "verdict": "positive"}, {"message_id": "m1", "verdict": "negative"})
        ),
        encoding="utf-8",
    )
    return audit, feedback


def test_저신뢰_질문만_모은다(logs):
    audit, _ = logs
    questions = find_low_confidence_questions(audit)
    assert len(questions) == 2
    assert "연차는 며칠?" not in questions


def test_문서_공백_리포트는_건수_순으로_나온다(logs):
    audit, _ = logs
    gaps = report_document_gaps(audit)
    assert gaps and gaps[0]["size"] >= gaps[-1]["size"]


def test_프롬프트_버전별로_신뢰도를_비교할_수_있다(logs):
    audit, _ = logs
    rows = {r["prompt_version"]: r for r in compare_versions(audit)}
    assert rows["v1"]["avg_confidence"] == 0.0
    assert rows["v2"]["avg_confidence"] == 1.0


def test_피드백이_골든셋_후보와_검토큐로_갈린다(logs):
    audit, feedback = logs
    result = collect_feedback_candidates(audit, feedback)
    assert [i["question"] for i in result["golden_candidates"]] == ["연차는 며칠?"]
    assert [i["question"] for i in result["review_queue"]] == ["출장비 정산 기한은?"]
