# 브랜치 현황

2026-10-01 기준. main에 머지된 것과 보관용(미채택) 실험 브랜치를 구분하기 위한 기록.
실험 브랜치는 전부 **삭제하지 않고 보존**한다 — 나중에 참고가 필요할 수 있어서.

| 브랜치 | 상태 | 설명 |
|---|---|---|
| `main` | 운영 | 실제 데모/최종 제출 코드. `ui-mes`(웹 UI+MES+RT-DETR 연동) + `ui-with-my-inspection`의 classify_model 최종검증이 머지됨 |
| `yuseong/ui-with-my-inspection` | 머지됨 → main | `0cf4a45`(classify_model 룰베이스 최종검증)이 main에 cherry-pick됨. 나머지 커밋은 이미 main에 있던 것과 동일 계보 |
| `origin/yuseong/ui-mes` | 머지됨 → main | 웹 UI(작업자 화면/분석) + MES(Spring Boot) 연동 + run_ui 카메라 메모리 + flip-h/v 옵션. 실제 데모 영상에서 `rtdetr:best.pt` + MES 콘솔로 확인된 그 구성 |
| `taein/mother-registration` | 보관 (미채택) | Mother 등록 기반 ROI 실험(`mother_registration.py`/`hole_assignment.py`/`occlusion.py`). main의 `src/geometry/roi_builder.py`/`association.py`가 같은 개념(Mother 기준 H1~H5 ROI 판정)을 독자적으로 더 완성된 형태로 이미 구현하고 있어 최종 데모/PPT 아키텍처와는 다른 계보로 확인됨 |
| `seungjae/state_machine` | 보관 (구버전) | main보다 오래된 지점 기준. association.py 로직 등은 main에 이미 더 발전된 형태로 흡수됨 |
| `origin/yuseong/web` | 보관 (구버전) | 웹 UI 초기 버전. `ui-mes`로 대체됨 |
| `origin/yuseong/ui-demo` | 보관 (구버전) | 웹 UI 중간 버전. `ui-mes`로 대체됨 |
| `experiment/rt-detr` | 머지됨 (동일) | main과 커밋까지 완전히 동일 |

## 판단 근거

- 최종 PPT(`5조_비전프로젝트 최종.pdf`) 부록의 팀 역할 분담과 대조
- 데모 영상(`머신비전_5조_AEGIS_동영상.mp4`) 실제 화면 캡처 — 상태 표시줄에 `rtdetr:best.pt` + MES 연동이 보여 `ui-mes` 계보가 실제 구동된 코드임을 확인
- 브랜치 간 `git diff --stat` / `git rev-list --left-right --count`로 커밋 그래프와 파일 변경 범위 비교
