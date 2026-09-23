# Mother 등록 + 조립 중 실시간 오류 검사

## 흐름

```
CHECK_MATERIALS ──READY 1초──▶ REGISTER_MOTHER ──손 뗀 상태 1초──▶ ASSEMBLING
   화면 전체 수량 비교            Mother 좌표·구멍 5개 실측 후 잠금       잠근 좌표로 구멍별 판정
```

`config/mvp.json`의 `registration.enabled`가 `false`면 기존 흐름(CHECK_MATERIALS → ASSEMBLING, 매 프레임 Mother OBB 비율 계산)으로 동작한다.

## REGISTER_MOTHER

작업자가 Mother만 윗면(구멍 5개)이 보이게 가로로 놓고 손을 뗀다. 아래 조건을 `register_stable_ms`(1초) 동안 만족하면 잠금.

| 조건 | 실패 코드 |
|---|---|
| 각도 ±`max_mother_angle_deg` | MOTHER_ANGLE_OUT_OF_RANGE |
| 길이/폭 3.8~6.5 (2구 ≈ 3.0) | MOTHER_SHAPE_MISMATCH |
| Mother 위에 볼트·나무조각 없음 | MOTHER_NOT_CLEAR |
| 구멍 5개 모두 보임 (옆면 2개, 3구 3개는 탈락) | MOTHER_HOLES_NOT_VISIBLE |
| 5개가 일직선·등간격 | MOTHER_HOLE_LAYOUT_MISMATCH |

구멍 위치는 `src/vision/hole_detector.py`가 이미지에서 실측한다(`service.update(frame, image)`). 이미지 없이 호출하면(JSONL 재생, 테스트) 설정 비율을 쓴다.

## ASSEMBLING

- 잠근 좌표 사용: 손/부품에 Mother가 가려지거나 미검출이어도 판정 계속.
- Mother가 끝까지 보이는 상태로 1초 이상 다른 위치에 있으면 재잠금(`MOTHER_RELOCKED` 이벤트, H1 방향 유지). 그 사이는 `MOTHER_MOVING` HOLD.
- 3초 이상 Mother가 전혀 안 보이면 `MOTHER_LOST` HOLD.
- 구멍 가림 기억(`src/process/occlusion.py`): 레시피에 맞게 끼워진 부품이 안 보이면 `occlusion_hold_ms`(1.5초) 동안 유지하고 `snapshot.occluded`에 표시. 잘못 끼운 부품은 기억하지 않으므로 빼면 NG가 바로 풀린다.
- 어느 구멍에도 연결되지 않는 부품이 Mother 위에 있으면(끼우는 중, 어긋남) 전체를 멈추지 않는다. 나머지 구멍은 계속 판정하고, PASS만 막는다(IN_PROGRESS). `ambiguous_report_ms`(1초) 넘게 계속되면 AMBIGUOUS_ASSOCIATION 메시지를 추가하고 화면에 보라색 `?`로 표시한다. (`registration.enabled=false`인 기존 흐름은 그대로 HOLD)
- Part ROI는 레시피 사진 실측값: 2구 length 0.48 / offset 0.14, 3구 length 0.70 / offset 0.28 (Mother 길이 비율).
- 판정은 기존 `evaluator.py` 그대로: WRONG_BOLT/WRONG_PART/UNEXPECTED_COMPONENT/EXTRA_COMPONENT/PART_ORIENTATION_ERROR → NG, MISSING_* → IN_PROGRESS.
- `service.reregister()`: Mother를 교체·크게 옮겼을 때 다시 등록(재료 확인 결과는 유지).

## Snapshot 추가 필드

- `registration`: `progress`(0~1), `measured`, `issues`, 잠금 후 `holes`(H1~H5 픽셀), `hole_local`
- `occluded`: 현재 기억으로 유지 중인 구멍 번호

작업자용 한글 문구는 `src/app/messages.py`의 `message(issue)`, `severity(issue)`.

## 실행

```
python -m scripts.live_registration --source 2           # 등록만 테스트
python -m scripts.live_inspection --recipe recipe_1 --source 2 --device 0
python -m scripts.check_registration --images sample_img  # 사진으로 등록 확인
python -m unittest tests.test_registered_flow tests.test_mother_registration tests.test_mvp tests.test_material_workflow
```

`live_inspection` 키: 1/2/3 레시피 변경, n 새 제품, r Mother 재등록, s 저장, q 종료. 이벤트는 `outputs/live_inspection/events_*.jsonl`.

CPU 추론이 250ms보다 느리면 매 프레임 FRAME_GAP HOLD가 난다. GPU(`--device 0`)를 쓰거나 테스트 때만 `--max-frame-gap-ms 500`.

## 한계

- 레시피 사진 3장 + 빈 Mother 사진으로만 확인. 실제 조립 영상(손 가림, 부품 들고 지나가기)으로 hold 시간과 Part ROI 보정 필요.
- Mother로 오검출된 다른 부품은 조립 단계에서 무시된다(판정 대상 아님).
- 세로 배치는 H1 방향이 모호해 등록을 거부한다.
