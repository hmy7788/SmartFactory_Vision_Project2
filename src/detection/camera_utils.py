"""
camera_utils.py

라이브 테스트 스크립트들이 공유하는 카메라 프레임 전처리 헬퍼.
"""

import cv2
import numpy as np

# DroidCam 무료 버전이 프레임에 박는 "using droidcam.app" 워터마크 위치.
# 640x480 프레임에서 실측한 값(x 18~233, y 208~221)에 여유를 둔 비율(x1, y1, x2, y2)이다.
# ⚠️ 다른 해상도/화면비로 받으면 위치가 달라질 수 있어서 그때는 다시 실측해야 한다.
DROIDCAM_WATERMARK_REL = (0.022, 0.428, 0.372, 0.466)


def remove_droidcam_watermark(frame):
    """워터마크 영역을 주변 배경으로 채워(inpaint) 검출/판정에 안 잡히게 한다."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = DROIDCAM_WATERMARK_REL
    mask = np.zeros((h, w), np.uint8)
    mask[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)] = 255
    return cv2.inpaint(frame, mask, 3, cv2.INPAINT_TELEA)
