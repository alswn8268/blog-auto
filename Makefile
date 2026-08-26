.PHONY: help up down setup index reindex app eval eval-log gaps purge test

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

up:      ## Qdrant + Ollama 기동
	docker compose up -d qdrant ollama

down:    ## 전체 종료
	docker compose down

setup:   ## Qdrant 컬렉션 생성
	python -m vectordb.setup

index:   ## data/raw 전체 색인
	python -m pipeline.build_index

reindex: ## 변경된 파일의 바뀐 조항만 재색인 (cron: 0 3 * * *)
	python -m features.auto_reindex

app:     ## Streamlit 실행
	streamlit run app/main.py

eval:    ## RAGAS 평가 (점수 하락 시 종료코드 1)
	python -m eval.run_ragas

eval-log: ## 지난 평가 이력 보기
	python -m eval.run_ragas --history

gaps:    ## 로그에서 개선 지점 추출
	python -m improvement.gap_analysis

purge:   ## 보존기간 지난 로그 파기 (cron: 30 3 * * *)
	python -m security.audit_log

test:    ## 순수 로직 단위 테스트 (모델 의존성 불필요)
	pytest -q
