"""Korean worker messages for Issue codes (UI / web / overlay share this)."""

NAMES = {"bolt_1": "노랑 볼트", "bolt_2": "주황 볼트", "part_2hole": "2구 나무조각",
         "part_3hole": "3구 나무조각", "mother_part": "Mother"}

PHASES = {"CHECK_MATERIALS": "1. 재료 확인", "REGISTER_MOTHER": "2. Mother 등록", "ASSEMBLING": "3. 조립 검사"}
STATUSES = {"READY": "재료 준비 완료", "IN_PROGRESS": "조립 중", "PASS": "완료 (PASS)",
            "NG": "오류 (NG)", "HOLD": "판정 대기"}

# Severity: error = worker must fix, info = progress guidance, wait = no judgement yet
ERROR_CODES = {"AMBIGUOUS_ASSOCIATION", "WRONG_BOLT", "WRONG_PART", "EXTRA_COMPONENT", "UNEXPECTED_COMPONENT",
               "PART_ORIENTATION_ERROR", "MATERIAL_EXCESS", "MATERIAL_UNEXPECTED"}
INFO_CODES = {"MISSING_BOLT", "MISSING_PART", "MATERIAL_MISSING", "MOTHER_REGISTERING"}

STATIC = {
    "MOTHER_NOT_FOUND": "Mother가 보이지 않습니다",
    "MULTIPLE_MOTHERS": "Mother가 여러 개 보입니다. 하나만 두세요",
    "MOTHER_ANGLE_OUT_OF_RANGE": "Mother를 가로로 놓아주세요",
    "MOTHER_SHAPE_MISMATCH": "Mother가 아닌 부품입니다",
    "MOTHER_NOT_CLEAR": "Mother 위의 부품을 치우고 손을 떼주세요",
    "MOTHER_HOLES_NOT_VISIBLE": "구멍 5개가 보이도록 윗면을 위로 놓아주세요",
    "MOTHER_HOLE_LAYOUT_MISMATCH": "구멍 배치가 Mother와 다릅니다",
    "HOLE_MEASUREMENT_UNAVAILABLE": "구멍 측정 불가",
    "MOTHER_REGISTERING": "손을 떼고 잠시 기다려주세요 (Mother 등록 중)",
    "MOTHER_MOVING": "Mother가 움직였습니다. 손을 떼면 다시 고정합니다",
    "MOTHER_LOST": "Mother가 오래 가려져 있습니다",
    "AMBIGUOUS_ASSOCIATION": "부품 위치가 애매합니다. 구멍에 정확히 맞춰주세요",
    "FRAME_GAP": "영상 지연 (추론 속도 부족)",
    "OUT_OF_ORDER_FRAME": "프레임 순서 오류",
    "INPUT_UNAVAILABLE": "카메라 입력 없음",
}


def name(value):
    return NAMES.get(value, value)


def _count(text):
    """'bolt_1:2' -> ('노랑 볼트', '2')"""
    component, _, count = text.partition(":")
    return name(component), count


def message(issue):
    code, hole = issue.code, f"H{issue.hole_id}"
    if code == "MISSING_BOLT":
        return f"{hole}: {name(issue.expected)}를 끼워주세요"
    if code == "MISSING_PART":
        return f"{hole}: {name(issue.expected)}을 연결해주세요"
    if code in ("WRONG_BOLT", "WRONG_PART"):
        return f"{hole}: {name(issue.expected)} 필요 (현재: {name(issue.observed)})"
    if code == "EXTRA_COMPONENT":
        return f"{hole}: 부품이 겹쳐 있습니다 ({', '.join(name(n) for n in issue.observed.split(','))})"
    if code == "UNEXPECTED_COMPONENT":
        return f"{hole}: 레시피에 없는 위치입니다 ({name(issue.observed)}) - 빼주세요"
    if code == "PART_ORIENTATION_ERROR":
        return f"{hole}: {name(issue.observed)} 방향을 Mother와 수직으로 맞춰주세요"
    if code == "AMBIGUOUS_ASSOCIATION" and issue.observed and not issue.observed[0].isdigit():
        parts = ", ".join(name(n) for n in issue.observed.split(","))
        return f"{parts}: 어느 구멍인지 불명확합니다. 구멍에 정확히 맞춰 끼워주세요"
    if code in ("MATERIAL_MISSING", "MATERIAL_EXCESS", "MATERIAL_UNEXPECTED"):
        component, need = _count(issue.expected)
        _, have = _count(issue.observed)
        verb = {"MATERIAL_MISSING": "부족", "MATERIAL_EXCESS": "초과", "MATERIAL_UNEXPECTED": "불필요"}[code]
        return f"재료 {verb}: {component} 필요 {need}개 / 현재 {have}개"
    return STATIC.get(code, code)


def severity(issue):
    if issue.code in ERROR_CODES:
        return "error"
    if issue.code in INFO_CODES:
        return "info"
    return "wait"
