"""RAGAS 평가 (명세 3장).

골든셋의 질문을 실제 파이프라인에 태워 답변·근거를 모은 뒤 faithfulness와
context_recall을 계산한다.

목표치: Faithfulness 0.75 이상. 이 아래로 나오면 청킹·프롬프트를 먼저 의심할 것.

실행: python -m eval.run_ragas --golden eval/golden_set.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

FAITHFULNESS_TARGET = 0.75


def collect_predictions(golden: list[dict], role: str | None = None) -> dict[str, list]:
    """골든셋 질문을 파이프라인에 태워 answer/contexts를 채운다."""
    from pipeline.query import answer_question

    questions, answers, contexts, ground_truths = [], [], [], []
    for i, item in enumerate(golden, 1):
        result = answer_question(item["question"], role=role, log=False)
        questions.append(item["question"])
        answers.append(result.answer)
        contexts.append([c.get("text", "") for c in result.contexts])
        ground_truths.append(item.get("ground_truth", ""))
        logger.info("[%d/%d] %s → 신뢰도 %s", i, len(golden), item["question"][:30], result.confidence)

    return {
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths,
    }


def run_evaluation(records: dict[str, list]):
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import context_recall, faithfulness

    dataset = Dataset.from_dict(records)
    return evaluate(dataset, metrics=[faithfulness, context_recall])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="골든셋으로 RAGAS 평가를 돌린다")
    parser.add_argument("--golden", default="eval/golden_set.json")
    parser.add_argument("--role", default=None, help="RBAC 역할을 씌워 평가")
    parser.add_argument("--limit", type=int, default=None, help="앞에서 N문항만")
    parser.add_argument("--out", default="eval/results.json")
    args = parser.parse_args()

    golden = json.loads(Path(args.golden).read_text(encoding="utf-8"))
    if args.limit:
        golden = golden[: args.limit]
    logger.info("골든셋 %d문항으로 평가합니다", len(golden))

    records = collect_predictions(golden, role=args.role)
    result = run_evaluation(records)
    print(result)  # 예: {'faithfulness': 0.82, 'context_recall': 0.77}

    scores = dict(result) if not isinstance(result, dict) else result
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps({"n": len(golden), "scores": {k: float(v) for k, v in scores.items()}},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    faith = float(scores.get("faithfulness", 0.0))
    if faith < FAITHFULNESS_TARGET:
        logger.warning(
            "Faithfulness %.3f < 목표 %.2f — 청킹 규칙과 프롬프트를 먼저 점검하세요.",
            faith, FAITHFULNESS_TARGET,
        )


if __name__ == "__main__":
    main()
