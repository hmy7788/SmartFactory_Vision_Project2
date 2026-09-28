# SmartFactory Vision — State Machine MVP

이 브랜치는 **재료 준비 확인 → 자동 조립 시작 → Mother 기준 ROI 조립 검사**를 구현한다. 모델 추론·기하·Recipe·시간 안정화를 분리하여 모델 없이도 테스트할 수 있다.

## AEGIS 시연 — 작업자 화면 + MES (브랜치 `yuseong/ui-mes`)

MES 가 작업지시(레시피 × 수량, 여러 줄이면 순서대로)를 MQTT 로 내려 보내면, 검사대 화면이 그 레시피로 재료 확인 → 조립 검사를 하고
[작업 완료] 마다 결과를 MES 로 올린다. 수량을 다 채우면 MES 가 대기열의 다음 작업지시를 자동으로 보낸다.

| 폴더 | 내용 |
|---|---|
| `web/` | 작업자 화면 (FastAPI + HTML/JS) · MES 연동 `web/mes_link.py` |
| `mes/` | MES 서버 (Spring Boot 3.5 · JPA/H2 · Paho MQTT) — [mes/README.md](mes/README.md) |
| `src/` | 판정 코어 (재료 확인 → 조립 검사) |

준비물: Python 3.10+ (`pip install -r requirements.txt`), Java 17+ (Temurin 21), [Mosquitto](https://mosquitto.org/download/) (Windows 설치판),
RT-DETR 가중치 `model/best.pt` (용량 때문에 Git 에서 제외 — 팀 공유 드라이브에서 받아 넣는다).
저장소는 **영문 경로**에 clone 한다 (MES 의 Gradle 이 한글 경로에서 실패한다).

1. `run_mes_demo.cmd` 더블클릭 → MQTT 브로커 · MES 서버(`http://localhost:8080`, 첫 실행은 jar 빌드 1~2분) · 검사대 화면(`http://127.0.0.1:8000`)
2. 카메라는 10초 안에 안 고르면 USB 웹캠(가장 큰 번호)으로 자동 선택
3. MES 콘솔에서 작업지시 발행 → 검사대가 받아 진행. [작업 완료] 뒤에는 완성품을 작업대에서 치우거나 분해해야 다음 재료 확인이 시작된다

자세한 내용: [MQTT 메시지](mes/docs/mes_mqtt.md) · [작업자 화면](docs/web.md) · [MES 서버](mes/README.md)

## 빠른 시작

Python 3.11+, 저장소 루트에서 실행한다. 코어와 테스트는 외부 패키지가 필요 없다.

```powershell
git clone --branch seungjae/state_machine --single-branch https://github.com/hmy7788/SmartFactory_Vision_Project2.git
cd SmartFactory_Vision_Project2
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m unittest discover -s tests -v
python -m scripts.replay_detections --demo --recipe recipe_1
```

합성 데모: 부족 → 초과 → 정확한 재료 → 조립 → PASS → H5 추가 NG → 수정 → Mother 유실/복귀. 가상 timestamp로 실행하며 실물 모델 성능 시험은 아니다.

## 모델로 샘플 검증

가중치는 기존 저장소 정책에 따라 Git에서 제외한다. 팀원이 전달한 OBB 가중치를 `model/yolo_obb_parts.pt`에 넣는다. [모델 안내](model/README.md) 참고.

```powershell
python -m pip install -r requirements-vision.txt
python -m scripts.visualize_rois --preview-outside-angle
python -m scripts.verify_materials --recipe recipe_1
```

- ROI 도구: sample_img 사진의 Mother/Hole/Bolt/Part ROI 표시. --model, --images, --config, --output 지원.
- 재료 도구: material_sample_*.jpg의 수량 검사. --recipe recipe_1/recipe_2/recipe_3/all 지원.
- 결과는 outputs/roi_debug 또는 outputs/material_debug의 실행시각 폴더에 PNG/JSON으로 저장된다.
- 초록 Mother, 노랑 Bolt ROI, 하늘색 2구/분홍 3구 Part ROI, 빨간 점 Hole.
- PREVIEW ONLY는 각도 초과 개발 표시이며 실제 조립 검사는 HOLD다.
- 정지 사진 READY는 재료 후보일 뿐 1초 안정화/자동 전환 검증이 아니다.

## 현재 공정 규칙

| 단계 | 검사 | 전환 |
|---|---|---|
| CHECK_MATERIALS | 카메라 전체 종류별 수량 정확 비교 | 정확한 구성이 1,000ms 유지되면 ASSEMBLING |
| ASSEMBLING | Hole별 Bolt/Part와 Recipe 비교 | PASS/NG/IN_PROGRESS/HOLD를 계속 갱신 |

부족은 IN_PROGRESS, 잘못된 종류/초과는 NG이며 준비 전환을 차단한다. 조립 단계에서는 전체 수량 검사를 종료한다. 가림·NG로 준비 단계에 돌아가지 않는다. 새 제품/Recipe 변경은 reset한다.

| Recipe | 요구 조립 (순서 자유) |
|---|---|
| recipe_1 | H1 bolt_1+part_2hole, H4 bolt_2+part_3hole |
| recipe_2 | H1/H3 각각 bolt_1+part_2hole |
| recipe_3 | H2 bolt_2+part_3hole |

준비 수량은 Mother 1개와 위 조합에서 산출한다. Hole 번호는 화면 왼쪽부터 H1~H5. Mother 수평 ±15° 범위에서 검사하고 Bolt/Part ROI 모두 함께 회전한다. Part는 Mother-local 위쪽(-v)에 놓인다. 물리적 360° 번호 추적은 지원하지 않는다. H5/비지정 Hole 추가 조립은 NG, 부족은 조립 중이다. 조립 판정 안정화는 400ms이며 PASS 후에도 재검사한다.

## 인수인계

- [API·출력·담당별 다음 작업](docs/state_machine_handoff.md)
- [샘플 검증 결과와 알려진 모델 오류](docs/validation_2026-09-22.md)
- [개발 가이드](state_machine_development_guidelines.md)
- [설정](config/mvp.json), [Recipe](config/recipes/recipe_1.json), [클래스 매핑](config/class_mapping.json)

기존 CLAUDE.md·전체 시스템 명세·학습/웹/분류 코드는 보존한다. 그 문서의 Zone 분할/순서별 Step 등은 이후 사용자와 합의한 이 브랜치 MVP와 다르다. **이번 코어에는 README와 인수인계 문서의 현재 규칙을 적용한다.**

## 완료 범위와 한계

44개 자동 테스트 및 합성 흐름 검증. 실제 OBB 모델의 정지 이미지 추론·재료 후보 검사까지 실행했다. 카메라 실시간 루프/GUI/DB/하드웨어는 아직 연결하지 않았다.

ROI 값은 UNVALIDATED_DEFAULTS로 실물 조립 사진에서 보정이 필요하다. 중간 학습 모델은 3구 Part를 Mother로 오분류하여 정상 준비 사진도 차단한다. confidence는 정확도가 아니며 95% 정확도/FPS/지연 목표는 아직 측정하지 않았다.

샘플 사진은 재현용으로 포함하며 outputs·모델 가중치·가상환경은 제외한다. 기존 requirements.txt는 전체 팀 환경, requirements-vision.txt는 이번 코어의 선택적 추론 환경이다.
