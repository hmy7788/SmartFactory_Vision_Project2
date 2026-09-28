# 2026-09-22 검증 결과

모델 yolo_obb_parts.pt, 매핑 config/class_mapping.json. 후보 confidence=0.25, 판정=0.5. 재료 검증은 imgsz=640 CPU. 아래는 제한된 샘플 결과이며 전체 정확도 아니다.

## 자동 테스트

44개 unittest 통과: 3종 Recipe, 정확/부족/초과/잘못된 재료, 준비 1초 전환, gap/reset/유실, 조립 단계 수량 집계 종료, 회전 ROI/Part 연결, 400ms 안정화, NG 복구 포함. 실제 영상 검증을 대체하지 않는다.

## 빈 Mother

mother_sample_1~4 모두 검출. 각도는 약 -0.3°, 26.6°, -2.8°, -2.7°. 샘플 2는 ±15° 범위 초과로 HOLD/preview only. Bolt와 Part ROI가 함께 회전하는 것을 확인했으며 실제 조립 overlap은 아직 보정 전이다.

## recipe_1 재료 확인

요구: Mother, 노랑 bolt_1, 주황 bolt_2, 2구 Part, 3구 Part 각각 1개.

| 사진 | 육안 구성 기준 기대 | 모델 기반 후보 | 검출 문제 |
|---|---|---|---|
| material_sample_1 | NG: 주황 2개/노랑 없음 | NG | 3구→Mother, 2구 미검출, 두 번째 주황 0.258로 집계 제외 |
| material_sample_2 | IN_PROGRESS: 2구 부족 | NG | 3구→Mother로 Mother 초과/3구 부족 오류 |
| material_sample_3 | IN_PROGRESS: 노랑·2구 부족 | NG | 3구→Mother 오분류 |
| material_sample_4 | READY: 요구 재료 완비 | NG | 3구→Mother(0.554) 오분류로 정상 준비 차단 |

4장 모두 NG지만 성공적인 오재료 검증이라고 해석하면 안 된다. 정상 샘플 4가 잘못 차단됐다. 매핑은 모델의 한글 클래스 그대로 연결하며 3구를 Mother로 바꾸는 로직은 없다. 샘플 4의 노랑에는 bolt_2 후보 0.384도 겹쳤으나 임계값에서 제외됐다.

빈 Mother 샘플과 촬영 배경/각도/크기 등이 다르다. 도메인 차이는 가능한 원인이지 이번 관측으로 확정된 원인은 아니다. 이 4장에 맞춰 confidence를 낮추거나 클래스를 강제 보정하지 않았다.

재현: python -m scripts.verify_materials --recipe recipe_1. outputs/material_debug 아래 PNG/JSON 생성. 정지 사진이므로 READY 후보만 검사하며 실시간 1초 전이는 별도 영상 검증이 필요하다.
