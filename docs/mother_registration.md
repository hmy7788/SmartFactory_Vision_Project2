# Mother 등록 + 조립 중 실시간 오류 검사

## 흐름

```
CHECK_MATERIALS ──READY 1초──▶ REGISTER_MOTHER ──손 뗀 상태 1초──▶ ASSEMBLING ──PASS 2초 / Enter──▶ RESULT
   화면 전체 수량 비교            Mother 좌표·구멍 5개 실측 후 잠금       잠근 좌표로 구멍별 판정         정답/오답 확정
                                                                           ▲                                │
                                                                           └──── reassemble() (오답 후 r) ───┤
                                                                     reset(recipe) (1/2/3) → CHECK_MATERIALS ┘
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

- 좌표 잠금: 손/부품에 Mother가 가려져도 판정 계속. 3초 이상 Mother가 전혀 안 보이면 `MOTHER_LOST` HOLD.
- 밀림 보정(`MotherTracker`): 크게 보이는 Mother 검출을 `follow_gain`(0.15)으로 따라가고, 구멍에 앉은 볼트(간격 30% 이내)를 기준점으로 `landmark_gain`(0.3)만큼 격자를 당긴다(최대 간격 30%). 5% 넘게 1초 이상 옮기면 재잠금(`MOTHER_RELOCKED`, H1 방향 유지), 그 사이는 `MOTHER_MOVING` HOLD.
- 구멍 배정(`src/geometry/hole_assignment.py`): 부품(볼트 중심, 나무조각 아래 끝)을 장축에 투영, 간격 단위 거리로 가장 가까운 구멍. `accept_ratio` 0.4 이내만 배정, 두 구멍 사이 경계는 ambiguous. 이전 프레임 배정은 다른 구멍 `switch_ratio` 0.3 안에 들어갈 때까지 유지. 수직에서 45° 넘게 누운 나무조각은 ambiguous(옮기는 중), 20~45°는 방향 오류 NG. Mother에 닿지 않는 부품은 무시.
- 누적 투표(`HoleEvidence`): 구멍·슬롯별 클래스 점수 = 이전×감쇠 + 신뢰도×가시성×(1−이전). Mother가 크게 안 보이는 프레임은 가시성 0.3. 다른 클래스가 보이면 기존 점수 약화. 레시피에 맞는 부품은 `evidence_keep_ms` 1400(안 보여도 약 1.5초 유지, `occluded`), 틀린 부품은 `evidence_drop_ms` 80(빼면 즉시 사라짐). 한 슬롯에 2개면 그대로 전달(EXTRA_COMPONENT).
- 애매한 부품: 전체 판정을 멈추지 않고 PASS만 막음(IN_PROGRESS). 1초 이상이면 AMBIGUOUS_ASSOCIATION(빨강 아님).
- 경고: 확정 NG가 `ng_alert_ms`(400) 더 유지되면 `snapshot.alert = "NG"`, `NG_ALERT` 이벤트(빨강 화면·경고음). 풀리면 `NG_CLEARED`.
- 판정은 기존 `evaluator.py`: WRONG_BOLT/WRONG_PART/UNEXPECTED_COMPONENT/EXTRA_COMPONENT/PART_ORIENTATION_ERROR → NG, MISSING_* → IN_PROGRESS.

## RESULT (최종 판정)

- 자동: 확정 PASS가 `pass_confirm_ms`(2초) 유지되면 정답 확정.
- 수동: `service.complete()`(Enter) — 확정 PASS면 정답, 아니면 오답(누락도 불량).
- `PRODUCT_RESULT` 이벤트와 `snapshot.result`: `product_seq`, `recipe_id`, `result`, `decided_by`(auto/manual), `issues`(최종), `issue_history`(조립 중 NG 이력), `assembly_ms`.
- 오답 후 `service.reassemble()` → 같은 Mother 잠금으로 ASSEMBLING 복귀. 다음 제품은 `service.reset(recipe)`. `product_seq`는 reset 후에도 이어진다.

## Snapshot 추가 필드

- `registration`: `progress`(0~1), `measured`, `issues`, 잠금 후 `holes`(H1~H5 픽셀), `hole_local`
- `occluded`: 현재 기억으로 유지 중인 구멍 번호
- `alert`: "NG"(빨강 경고 중) 또는 ""
- `result`: RESULT 단계의 최종 판정

작업자용 한글 문구는 `src/app/messages.py`의 `message(issue)`, `severity(issue)`.

## 실행

```
python -m scripts.live_registration --source 2           # 등록만 테스트
python -m scripts.live_inspection --recipe recipe_1 --source 2 --device 0
python -m scripts.check_registration --images sample_img  # 사진으로 등록 확인
python -m unittest tests.test_registered_flow tests.test_mother_registration tests.test_mvp tests.test_material_workflow
```

`live_inspection` 키: Enter 조립 완료(최종 판정), r 오답 후 재조립 / 그 외 Mother 재등록, 1/2/3 다음 제품(레시피), n 같은 레시피 다음 제품, m 소리, s 저장, q 종료. 기록은 `outputs/live_inspection/events_*.jsonl`, `results_*.csv`.

CPU 추론이 250ms보다 느리면 매 프레임 FRAME_GAP HOLD가 난다. GPU(`--device 0`)를 쓰거나 테스트 때만 `--max-frame-gap-ms 500`.

## 한계

- 레시피 사진 3장 + 빈 Mother 사진으로만 확인. 실제 조립 영상(손 가림, 부품 들고 지나가기)으로 hold 시간과 Part ROI 보정 필요.
- Mother로 오검출된 다른 부품은 조립 단계에서 무시된다(판정 대상 아님).
- 세로 배치는 H1 방향이 모호해 등록을 거부한다.
