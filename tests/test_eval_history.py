"""RAGAS 상시 평가 — 이력 저장과 회귀 감지 (7장 1단계)."""

import json

import pytest

from eval.history import (
    REGRESSION_TOLERANCE,
    append_run,
    below_target,
    config_snapshot,
    detect_regressions,
    read_history,
    summarize,
)


@pytest.fixture
def history(tmp_path):
    return tmp_path / "history.jsonl"


def test_실행마다_점수와_설정이_함께_쌓인다(history):
    append_run({"faithfulness": 0.82, "context_recall": 0.77}, 25, history)
    entries = read_history(history)

    assert entries[0]["scores"]["faithfulness"] == 0.82
    assert entries[0]["n_questions"] == 25
    # 설정을 함께 남겨야 점수 차이의 원인을 되짚을 수 있다
    assert "prompt_version" in entries[0]["config"]
    assert "multi_query_n" in entries[0]["config"]


def test_설정_스냅샷이_검색_파라미터를_담는다():
    snapshot = config_snapshot()
    for key in ("fusion", "retrieve_top_k", "rerank_top_k", "multi_query_n", "routing_enabled"):
        assert key in snapshot


def test_직전_대비_떨어지면_회귀로_잡는다():
    regressions = detect_regressions({"faithfulness": 0.71}, {"faithfulness": 0.82})
    assert len(regressions) == 1
    assert regressions[0].metric == "faithfulness"
    assert regressions[0].drop == pytest.approx(0.11)


def test_평가_흔들림_수준의_차이는_회귀로_보지_않는다():
    # LLM 판정에는 편차가 있어, 작은 차이까지 회귀로 잡으면 매일 거짓 경보가 뜬다
    small = REGRESSION_TOLERANCE / 2
    assert detect_regressions({"faithfulness": 0.80 - small}, {"faithfulness": 0.80}) == []


def test_점수가_올랐으면_회귀가_아니다():
    assert detect_regressions({"faithfulness": 0.90}, {"faithfulness": 0.82}) == []


def test_첫_실행은_비교_대상이_없다():
    assert detect_regressions({"faithfulness": 0.5}, None) == []
    assert detect_regressions({"faithfulness": 0.5}, {}) == []


def test_새로_생긴_지표는_비교하지_않는다():
    assert detect_regressions({"answer_relevancy": 0.4}, {"faithfulness": 0.9}) == []


def test_목표치_미달을_알려준다():
    assert below_target({"faithfulness": 0.71})
    assert not below_target({"faithfulness": 0.80})


def test_이력이_없어도_요약이_깨지지_않는다(history):
    assert summarize(history) == []


def test_깨진_줄은_건너뛴다(history):
    good = {"timestamp": "2026-08-26T10:00:00", "n_questions": 3,
            "scores": {"faithfulness": 0.8}, "config": {}}
    history.write_text(json.dumps(good, ensure_ascii=False) + "\n깨진 줄\n", encoding="utf-8")
    assert len(read_history(history)) == 1
