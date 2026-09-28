# 모델 배치 안내

기존 저장소 정책에 따라 *.pt는 Git에서 제외한다. 팀에서 전달받은 학습 OBB 체크포인트를 이 폴더의 yolo_obb_parts.pt로 저장한다. 가중치 없이도 코어 테스트/합성 데모는 실행할 수 있다.

클래스: 볼트_주황, 볼트_노랑, 나무_5구멍, 나무_3구멍, 나무_2구멍. config/class_mapping.json으로 내부 이름을 연결한다. 일반 pretrained yolov8n-obb.pt는 프로젝트 모델이 아니다.

현재 모델은 중간 학습본으로 3구→Mother 혼동이 있다. docs/validation_2026-09-22.md 참고. 모델 교체 시 버전/해시를 기록하고 샘플을 재검증한다.

다른 모델(YOLO26 · RT-DETR · YOLO detect …)도 이 폴더에 넣고 `run_ui.cmd` 로 고르면 된다. 클래스 이름이 다르면 가중치 옆에 `<가중치이름>.classes.json` — [docs/model_swap.md](../docs/model_swap.md).
