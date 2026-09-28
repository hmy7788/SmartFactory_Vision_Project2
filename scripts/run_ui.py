"""모델 하나를 골라 작업자 UI 를 띄운다 — 팀원 각자의 가중치로 같은 화면·같은 판정을 돌려 보는 용도.

    python -m scripts.run_ui                              # model/*.pt 중에서 고르기 → 카메라 번호 고르기 → 브라우저 자동
    python -m scripts.run_ui model/my_yolo26.pt           # 가중치 지정
    python -m scripts.run_ui model/my.pt 조립영상.mp4      # 웹캠 대신 녹화 영상 (원래 속도로 재생, 판정은 같다)
    python -m scripts.run_ui model/my.pt --camera 1       # 카메라 번호를 바로 (묻지 않음)
    python -m scripts.run_ui --demo                       # 모델·카메라 없이 합성 데모 화면

    윈도우: run_ui.cmd 를 더블클릭하거나, .pt / 영상 파일을 run_ui.cmd 위에 끌어다 놓는다.

여기서 모르는 옵션은 그대로 web.server 로 넘어간다: --imgsz 480 --conf 0.3 --port 8001 --recipe recipe_2 --class-map … --model-type rtdetr
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v"}


CAMERA_PROMPT_S = 10                        # 카메라 번호를 이 시간 안에 안 고르면 기본값 — MES 시연에서 창을 안 봐도 검사대가 뜨게


def ask(prompt: str, default: str, timeout: float | None = None) -> str:
    if timeout is None:
        try:
            got = input(f"{prompt} [{default}]: ").strip()
        except EOFError:
            got = ""
        return got or default
    print(f"{prompt} [{default}]  ({timeout:.0f}초 안에 안 고르면 {default}): ", end="", flush=True)
    box: list[str] = []
    reader = threading.Thread(target=lambda: box.append(sys.stdin.readline()), daemon=True)
    reader.start()
    reader.join(timeout)
    if not box:                             # 아무도 안 눌렀다
        print(f"\n  → {default}")
        return default
    return box[0].strip() or default


def pick_weights() -> Path | None:
    found = sorted(p for p in (ROOT / "model").glob("*.pt") if "classifier" not in p.name.lower())
    if not found:
        print("model/ 폴더에 검출 가중치(.pt)가 없습니다. 받은 .pt 를 model/ 에 넣거나 run_ui.cmd 위에 끌어다 놓으세요.")
        return None
    if len(found) == 1:
        return found[0]
    print("model/ 의 가중치:")
    for i, p in enumerate(found, 1):
        print(f"  [{i}] {p.name}  ({p.stat().st_size / 1e6:.1f} MB)")
    default = next((i for i, p in enumerate(found, 1) if p.name == "yolo_obb_parts.pt"), 1)
    while True:
        got = ask("사용할 번호", str(default))
        if got.isdigit() and 1 <= int(got) <= len(found):
            return found[int(got) - 1]
        print("  목록의 번호를 입력하세요")


LAST_CAMERA = ROOT / "data" / "last_camera.txt"   # 지난번에 쓴 카메라 번호 — 다음 실행의 기본값
CAMERA_RETRIES = 2                                  # 카메라가 덜 잡히면 2초 간격으로 다시 찾는 횟수


def _scan_cameras(cv2, backend) -> list[int]:
    found = []
    print("카메라 찾는 중 …")
    for i in range(4):
        cap = cv2.VideoCapture(i, backend)
        ok = cap.isOpened() and cap.read()[0]
        if ok:
            found.append(i)
            w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"  {i}: {w}x{h}")
        cap.release()
    return found


def pick_camera(sleep=time.sleep) -> int:
    try:
        import cv2
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
        except Exception:
            pass
    except ImportError:
        return 0
    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
    try:
        last = int(LAST_CAMERA.read_text().strip())
    except (OSError, ValueError):
        last = None
    # 방금 끈 검사 화면이 USB 웹캠을 아직 놓지 않았으면 그 카메라가 목록에서 빠진다 → 내장 카메라가 기본이 되어 버린다 (09-28).
    # 지난번 카메라가 안 보이거나 카메라가 하나뿐이면 잠깐 기다렸다가 다시 찾는다.
    found = _scan_cameras(cv2, backend)
    for _ in range(CAMERA_RETRIES):
        if (last is None or last in found) and len(found) >= 2:
            break
        print("  카메라가 덜 잡혔습니다 — 2초 뒤 다시 찾습니다 (방금 끈 화면이 카메라를 놓는 중일 수 있음)")
        sleep(2)
        found = sorted(set(found) | set(_scan_cameras(cv2, backend)))
    if not found:
        print("  열리는 카메라가 없습니다 (USB 연결 · 줌/팀즈가 카메라를 잡고 있는지 확인). 0번으로 시도합니다.")
        return 0
    default = last if last in found else max(found)     # 지난번 카메라, 없으면 나중에 꽂은 USB 웹캠(보통 가장 큰 번호)
    print("  노트북 내장은 보통 0, USB 웹캠은 보통 1" + (f" · 지난번 {last}" if last is not None else ""))
    got = ask("카메라 번호", str(default), timeout=CAMERA_PROMPT_S)
    cam = int(got) if got.isdigit() else default
    try:
        LAST_CAMERA.parent.mkdir(parents=True, exist_ok=True)
        LAST_CAMERA.write_text(str(cam))
    except OSError:
        pass
    return cam


def open_browser_when_ready(port: int) -> None:
    url = f"http://127.0.0.1:{port}"
    for _ in range(240):                    # 모델 로딩이 길어도 최대 2분 기다린다
        try:
            urllib.request.urlopen(url, timeout=1)
            webbrowser.open(url)
            print(f"\n브라우저: {url}   (끄려면 이 창에서 Ctrl+C)\n")
            return
        except Exception:
            time.sleep(0.5)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help=".pt 가중치 그리고/또는 영상 파일 (순서 무관)")
    ap.add_argument("--camera", type=int, default=None)
    ap.add_argument("--demo", action="store_true", help="모델·카메라 없이 합성 데모")
    ap.add_argument("--no-browser", action="store_true")
    a, rest = ap.parse_known_args(sys.argv[1:] if argv is None else argv)

    from web import server
    if a.demo:
        args = server.parse(["--source", "demo", *rest])
        if not a.no_browser:
            threading.Thread(target=open_browser_when_ready, args=(args.port,), daemon=True).start()
        server.serve(args)
        return 0

    weights = video = None
    for f in a.files:
        p = Path(f)
        if p.suffix.lower() == ".pt":
            weights = p
        elif p.suffix.lower() in VIDEO_EXT:
            video = p
        else:
            print(f"무슨 파일인지 모르겠습니다 (.pt 나 영상만): {f}"); return 1
    weights = weights or pick_weights()
    if weights is None:
        return 1
    if not weights.exists():
        print(f"가중치 파일이 없습니다: {weights}"); return 1

    # 모델은 여기서 한 번만 연다 → 서버에 그대로 넘긴다.
    from ultralytics import RTDETR, YOLO
    mt = rest[rest.index("--model-type") + 1] if "--model-type" in rest else "rtdetr"
    print(f"\n가중치 여는 중: {weights} ({mt}) …")
    try:
        preloaded = RTDETR(str(weights)) if mt == "rtdetr" else YOLO(str(weights))
    except Exception as error:
        print(f"!! 이 파일을 열 수 없습니다: {type(error).__name__}: {error}")
        print("   ultralytics 버전이 모델보다 낮으면 (예: YOLO26) pip install -U ultralytics")
        return 1

    server_argv = ["--source", "camera", "--weights", str(weights)]
    if video:
        server_argv += ["--video", str(video)]
    else:
        cam = a.camera if a.camera is not None else pick_camera()
        server_argv += ["--camera", str(cam)]
    args = server.parse(server_argv + rest)
    print()
    if not a.no_browser:
        threading.Thread(target=open_browser_when_ready, args=(args.port,), daemon=True).start()
    try:
        server.serve(args, preloaded)
    except SystemExit as stop:               # 클래스 이름 불일치 등 — 안내를 남기고 끝낸다
        if stop.code not in (None, 0):
            print(f"\n=== {stop.code}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
