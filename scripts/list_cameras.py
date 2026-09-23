"""연결된 카메라를 0~4번까지 열어 보고 되는 것만 보여 준다.

    python -m scripts.list_cameras
    0: 1280x720   OK
    1: 640x480    OK
    2~4: 없음
"""
import sys


def main():
    try:
        import cv2
    except ImportError:
        print("opencv(cv2) 가 없습니다 — install.cmd 먼저"); return 1
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)   # "can't open camera" 경고 숨김
    except Exception:
        pass
    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY   # 윈도우는 DSHOW 가 훨씬 빨리 열린다
    found = []
    for i in range(5):
        cap = cv2.VideoCapture(i, backend)
        ok = cap.isOpened()
        if ok:
            ok, img = cap.read()
        if ok:
            h, w = img.shape[:2]
            found.append(i)
            print(f"  {i}: {w}x{h}   OK")
        cap.release()
    if not found:
        print("  열리는 카메라가 없습니다. USB 연결·다른 프로그램(줌, 팀즈)이 카메라를 잡고 있는지 확인")
        return 1
    print(f"\n  → 사용할 번호를 고르세요. 노트북 내장은 보통 0, 나중에 꽂은 USB 웹캠은 보통 1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
