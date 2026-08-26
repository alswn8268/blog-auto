#!/usr/bin/env bash
# 색인 → 질의까지 한 번에 확인하는 스모크 테스트.
# Qdrant와 Ollama가 떠 있어야 한다 (make up).
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== 1. Ollama 상태 =="
python -c "from llm.generate import health_check; ok, msg = health_check(); print(msg); raise SystemExit(0 if ok else 1)"

echo "== 2. 컬렉션 생성 =="
python -m vectordb.setup

echo "== 3. 샘플 문서 색인 =="
python -m pipeline.build_index --dir data/samples

echo "== 4. 질의 =="
python -m pipeline.query "연차휴가는 며칠인가요?"
