RT-DETR-L 추론 테스트 사진 (test셋 149장 중 선별) — 원본: runs/rtdetr_test/full_run/

클래스별 단일 부품 (검은 배경, 손 없음)
  clean_bolt_1.jpg        bolt_1_008.jpg        conf 0.93
  clean_bolt_2.jpg        bolt_2_004.jpg        conf 0.92
  clean_mother_part.jpg   mother_part_005.jpg   conf 0.97 (살짝 기울어짐 — AABB라 배경 포함 여유 있는 것도 보임)
  clean_part_2hole.jpg    part_2hole_026.jpg    conf 0.97
  clean_part_3hole.jpg    part_3hole_002.jpg    conf 0.98

손에 가려진 상태 (픽킹 영상 프레임)
  hand_bolt_1.jpg         b_frame00027_004...jpg       conf 0.88
  hand_mother_part.jpg    5_hole_frame00011_001...jpg  conf 0.96
  hand_part_2hole.jpg     2_hole_frame00075_007...jpg  conf 0.97
  hand_part_3hole.jpg     3_hole_frame00118_019...jpg  conf 0.96

⚠️ bolt_2(주황 볼트)는 손 가림 사진이 없음 — 픽킹 영상 데이터셋 자체에 bolt_2를 손으로
   집는 프레임이 없어서(train+test 전체 라벨 확인함, "b_frame" 소스는 전부 bolt_1뿐) 대체
   불가. 필요하면 bolt_2 픽킹 영상을 새로 촬영해야 함.

권장 슬라이드 구성: 클래스별 clean/hand 사진을 위아래로 짝지어서(2행 5열, bolt_2는 clean만)
"손으로 가려도 검출 유지"를 대비시켜 보여주면 됨.

---

all_149/ — test셋 149장 전체 추론 결과 (원본 파일명 그대로, 직접 검수용)
  runs/rtdetr_test/full_run/ 전체를 그대로 복사한 것. 구성:
    단일 부품(bolt_1/bolt_2/mother_part/part_2hole/part_3hole)   84장
    조립체(model_a/b/c)                                          15장
    픽킹 영상 손 포함(2_hole/3_hole/5_hole/b_frame)               20장
    조립 진행중(recipe1/2/3_process, recipe3_frame)               30장
    합계                                                        149장
  전부 확인 필요한 이상 케이스: model_b_029.png (mother_part 중복 검출, docs/rt-detr-experiment.md 참고)
