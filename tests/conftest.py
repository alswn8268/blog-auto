import sys
from pathlib import Path

# 프로젝트 루트를 임포트 경로에 넣는다 (패키지 설치 없이 pytest 실행)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
