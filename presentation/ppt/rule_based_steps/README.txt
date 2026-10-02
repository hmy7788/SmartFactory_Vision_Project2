룰베이스 슬라이드용 사진 — 어떤 사진을 몇 번 단계에 쓸지 정리

1/3/4단계 (컨투어 검출 · 구멍 개수 세기 · 시그니처 대조) — 한 장으로 다 보여줌
  원본: step1_3_4_contour_count_signature_before.png (model_a_006, 정상 Model A)
  결과: step1_3_4_contour_count_signature_debug.png
  - 파란 선 = 검출된 외곽선(컨투어)
  - 초록 원 = "접합점 위쪽" 빈 구멍 (왼쪽 세로막대 1개, 오른쪽 세로막대 2개 → [2,1] = Model A)
  - 좌상단 텍스트에 vertical_signature=[2, 1] 그대로 찍혀 있어서 3·4단계 설명에 바로 씀
  - 회전이 거의 없는(rotation=0.2deg) 사진이라 1/3/4단계 설명용으로 깔끔함

2단계 (회전 보정) — before/after 쌍
  원본(기울어짐): step2_rotation_before.png (model_b_024, 58도 기울어진 Model B)
  결과(보정 후): step2_rotation_debug.png
  - "rotation=57.9deg"를 감지해 수평으로 되돌린 뒤에도 정확히 [1, 1] = Model B로 판별
  - 원본은 거의 안 보일 정도로 어둡게 나와서(저조도), 필요하면 밝기만 살짝 올려서 써도 됨

5단계 (배치 검증 — 구조는 맞아도 위치·색이 틀리면 NG) — 실제 실패 사례
  원본: step5_placement_error_before.png (model_b_029)
  결과: step5_placement_error_debug.png
  - 구멍 개수로는 [1, 1] = Model B와 일치하지만, 왼쪽 접합점이 "bolt_2"(주황)로 감지돼
    Model B 규정 색(bolt_1, 노랑)과 달라 실제로 NG 처리된 진짜 사례
  - "구조만 보면 통과하는데 배치 검증이 마지막에 잡아낸다"는 스토리에 가장 좋은 예시

권장 슬라이드 배치
  - 1/3/4단계 카드 3개 옆에 step1_3_4_contour_count_signature_debug.png 하나만 크게
  - 2단계 카드 옆에 before/after 두 장을 나란히 (회전 보정 시각적 대비)
  - 5단계 카드 옆에 step5_placement_error_debug.png (또는 before도 같이, "이렇게 보이지만 사실 색이 다름")
