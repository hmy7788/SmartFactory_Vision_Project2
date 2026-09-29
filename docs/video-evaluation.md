# 영상 평가 기능 사용법

현재 브랜치의 검사 로직을 그대로 실행하며 매 프레임 로그를 저장한다. 평가를 위해 phase를 강제로 전환하지 않는다. 새 브랜치의 검사 로직이 과거 실행과 다를 수 있으므로 metadata의 git 커밋 및 config를 비교한다.

## 실행

```powershell
Set-Location C:\dev\poka_yoke\.publish-checkout
python -m scripts.live_inspection --video ../eval_vid.mp4 --recipe 1 --model-type yolo-obb --weights ../model/yolo26_obb_parts_50.pt --device cpu --no-window --eval-log outputs/eval/obb_run03
python -m scripts.evaluate_video --annotation ../evaluation/annotations/eval_vid.json --run outputs/eval/obb_run03 --output outputs/eval/obb_run03_report
```

출력 폴더가 이미 존재하면 새 이름을 지정한다. 기존 결과는 덮어쓰지 않는다. 설치 확인 시 `--max-frames 10`을 붙일 수 있지만 이는 부분 실행으로 최종 성능 비교에 사용하지 않는다.

## 로그 및 결과

- metadata.json: 모델/영상 SHA256, recipe, config, device, imgsz, 버전, git 브랜치/커밋, 완료 여부.
- predictions.jsonl: 영상 PTS, 검출 결과, 후보/확정 판정과 오류 원인, 처리 시간. 프레임마다 flush.
- metrics.json: 전체·구간·사건 지표와 한계.
- segments.csv / events.csv / report.md: 구간 및 사건 표, 요약.

기본 영상 시간은 PTS다. 일정하지 않은 FPS도 원본 시간으로 비교한다. 증가하지 않는 PTS는 오류이며 고정 FPS 영상임을 확인한 경우에만 `--video-clock cfr`를 사용한다. 처리 시간은 read부터 HUD까지 측정하며 저장/표시 I/O를 제외한다. 오프라인 FPS는 실제 카메라-to-UI 지연이 아니다.

## 채점 규칙

- 이전 평가와 동일한 schema 1을 사용한다. 기존 obb_run01/02 로그도 재채점할 수 있다.
- 상태 정답 null은 정확도에서 제외한다. HOLD 정답으로 바꾸지 않는다.
- 상태 정확도는 영상 시간 가중이며 phase 정확도는 별도다.
- 오류 사건은 명확한 NG 구간에 한 번 이상 확정 NG가 있으면 검출 성공이다. 원인 일치 여부와 경고 유지 시간 비율도 함께 본다.
- 원인 일치 판정은 confirmed issues를 사용한다. 과거 확정 NG에 현재 candidate의 원인을 붙이지 않는다.
- 부분 실행은 provisional로 표시하고 완전히 커버한 사건만 요약 분모에 넣는다. 커버리지를 반드시 함께 보고한다.
- `--grace-ms`가 없고 정답 정책도 null이면 유예 0ms의 raw 점수다. 합격 기준이 아니다.
- 오류 최초 관찰 시점이 없으면 지연은 null이다. 미관측 지연을 0으로 만들지 않는다.
- 원본 영상 SHA256이 다른 로그는 기본 거부한다.

상세 지표 정의는 `outputs/eval/evaluation_methodology_ko.md`와 정답 설명을 참고한다.

## 변경 사항 보존

코드 수정 후 `git status --short`로 변경 파일을 확인한다. 완성된 작업은 해당 브랜치에 커밋하면 보존된다. 미완성 작업을 임시 보관하려면 `git stash push -u`로 untracked 파일까지 보관한다. 커밋과 push/PR은 서로 별개다.

현재 기능 복원 작업에서는 자동 커밋·푸시·PR을 수행하지 않는다. 브랜치 전환 전에 코드 보존 여부를 확인한다. `outputs/`는 Git ignore 대상이므로 평가 로그·리포트는 별도의 백업 대상으로 관리한다.
