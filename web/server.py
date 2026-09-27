"""웹 서버 — 정적 화면 + WebSocket(/ws) + REST(/api/*) + MJPEG(/video).

    python -m web.server                       # 합성 데모 (카메라·모델 없음)
    python -m web.server --source jsonl --jsonl detections.jsonl
    python -m web.server --source camera       # web/source.py 의 CameraSource 를 채운 뒤

브라우저: http://localhost:8000

Starlette 로 짰다. FastAPI 는 Starlette 위의 얇은 층이고(설치하면 같이 온다), 이 서버는 요청 본문 검증이
없어서 그 층이 할 일이 없다. FastAPI 데코레이터로 바꾸고 싶으면 라우트 함수는 그대로 두고 등록만 바꾸면 된다.
"""
from __future__ import annotations

import argparse
import importlib.util
import asyncio
import contextlib
import json
import threading
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from src.app.config import load_config
from web.pipeline import Pipeline
from web.source import DEFAULT_WEIGHTS, CameraSource, DemoSource, JsonlSource, demo_config
from web.store import Store

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).with_name("static")


class NoCacheStatic(StaticFiles):
    """화면 파일(app.js·css) 을 브라우저가 캐시로 계속 쓰지 않게 — 매번 서버에 확인(ETag, 안 바뀌었으면 304).
    이게 없으면 파일을 바꿔도 F5 로는 옛 화면이 뜬다 (Chrome 은 하위 리소스를 일반 새로고침 때 재검증하지 않는다)."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


class Hub:
    """파이프라인 스레드 → 접속한 브라우저 전부. 마지막 payload 는 새 접속과 /api/state 에 바로 준다."""

    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[WebSocket] = set()
        self.last: dict | None = None
        self.last_jpeg: bytes | None = None
        self.jpeg_event = threading.Event()

    def publish(self, payload: dict, jpeg: bytes | None) -> None:      # 파이프라인 스레드에서 불린다
        self.last = payload
        if jpeg is not None:
            self.last_jpeg = jpeg
            self.jpeg_event.set()
        if self.loop is not None and self.clients:
            self.loop.call_soon_threadsafe(self._fanout, json.dumps(payload, ensure_ascii=False))

    def _fanout(self, text: str) -> None:
        for ws in list(self.clients):
            asyncio.ensure_future(self._send(ws, text))

    async def _send(self, ws: WebSocket, text: str) -> None:
        try:
            await ws.send_text(text)
        except Exception:
            self.clients.discard(ws)


def create_app(pipeline: Pipeline, store: Store, hub: Hub) -> Starlette:
    def q(request: Request, name: str, default, cast=str):
        raw = request.query_params.get(name)
        if raw is None or raw == "":
            return default
        if cast is bool:
            return raw.lower() in ("1", "true", "yes", "on")
        return cast(raw)

    async def index(request):
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        hub.clients.add(ws)
        try:
            if hub.last is not None:
                await ws.send_text(json.dumps(hub.last, ensure_ascii=False))
            while True:
                await ws.receive_text()               # 브라우저는 보낼 게 없다. 끊김 감지용
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(ws)

    async def video(request):
        if not pipeline.source.has_video:
            return JSONResponse({"error": "이 소스는 영상이 없습니다 (demo/jsonl). 화면은 오버레이만 그립니다."}, 404)

        async def gen():
            loop = asyncio.get_running_loop()
            while True:
                await loop.run_in_executor(None, hub.jpeg_event.wait, 1.0)
                hub.jpeg_event.clear()
                if hub.last_jpeg:
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                           + str(len(hub.last_jpeg)).encode() + b"\r\n\r\n" + hub.last_jpeg + b"\r\n")
        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    # ── 상태 · 명령 ──
    async def state(request):
        return JSONResponse(hub.last or {"type": "snapshot", "waiting": True, "status": "HOLD",
                                         "phase": "CHECK_MATERIALS"})

    async def recipes(request):
        # 레시피 탭이 부른다 — 여기서 파이프라인 목록도 같이 갱신해야 헤더 드롭다운과 어긋나지 않는다
        return JSONResponse({"current": pipeline.recipe.recipe_id, "recipes": pipeline.refresh_recipes()})

    async def select_recipe(request):
        rid = request.path_params["recipe_id"]
        try:
            pipeline.select_recipe(rid)
        except KeyError:
            return JSONResponse({"ok": False, "reason": f"unknown recipe {rid}"}, 404)
        except PermissionError as error:             # MES 연동 중 — 레시피는 작업지시가 정한다
            return JSONResponse({"ok": False, "reason": str(error)}, 409)
        return JSONResponse({"ok": True, "recipe_id": rid})

    async def reset(request):
        pipeline.reset()
        return JSONResponse({"ok": True})

    async def complete(request):
        result = await asyncio.get_running_loop().run_in_executor(None, pipeline.complete)
        return JSONResponse(result, 200 if result.get("ok") else 409)

    async def config(request):
        return JSONResponse(pipeline.config)

    # ── 이력 · 분석 · 진단 (Store 읽기) ──
    async def history(request):
        return JSONResponse(store.history(
            limit=q(request, "limit", 50, int), recipe_id=q(request, "recipe_id", None),
            result=q(request, "result", None), ng_only=q(request, "ng_only", False, bool),
            hold_only=q(request, "hold_only", False, bool)))

    async def timeline(request):
        return JSONResponse(store.timeline(int(request.path_params["product_id"])))

    async def analytics(request):
        days = q(request, "days", 7, int)
        return JSONResponse({"days": days, "fpy": store.fpy(days), "fpy_daily": store.fpy_daily(days),
                             "cycle": store.cycle(days), "pareto": store.pareto(days),
                             "material_pareto": store.pareto(days, phase="CHECK_MATERIALS"),
                             "heatmap": store.heatmap(days), "recovery": store.recovery(days)})

    async def diagnostics(request):
        days, hours = q(request, "days", 7, int), q(request, "hours", 1, int)
        return JSONResponse({"hold_reasons": store.hold_reasons(days), "confidence": store.confidence(days),
                             "metrics": store.metrics(hours), "config": pipeline.config, "run_id": pipeline.run_id})

    @contextlib.asynccontextmanager
    async def lifespan(app):
        hub.loop = asyncio.get_running_loop()
        yield
        pipeline.stop()
        if pipeline.mes is not None:
            pipeline.mes.stop()

    return Starlette(lifespan=lifespan, routes=[
        Route("/", index),
        WebSocketRoute("/ws", ws_endpoint),
        Route("/video", video),
        Route("/api/state", state),
        Route("/api/recipes", recipes),
        Route("/api/recipe/{recipe_id}", select_recipe, methods=["POST"]),
        Route("/api/reset", reset, methods=["POST"]),
        Route("/api/complete", complete, methods=["POST"]),
        Route("/api/config", config),
        Route("/api/history", history),
        Route("/api/timeline/{product_id:int}", timeline),
        Route("/api/analytics", analytics),
        Route("/api/diagnostics", diagnostics),
        Mount("/static", NoCacheStatic(directory=str(STATIC)), name="static"),
    ])


def build(args, preloaded=None) -> tuple[Starlette, Pipeline, Store, Hub]:
    """preloaded = 미리 연 ultralytics 모델 객체. scripts.run_ui 가 이미 연 모델을 다시 열지 않게."""
    # --config 를 안 줬으면: demo/jsonl 은 데모 시나리오가 맞춰 짜인 config/mvp.json(±15°, 위쪽만,
    # 좌우뒤집힘 불허), 실제 카메라는 config/rtdetr_live.json(각도 89.9°, 좌우뒤집힘 허용, 부품은
    # 위쪽만 — 아래쪽은 PART_WRONG_SIDE 로 NG. 단, 조립체 전체가 180도 돈 경우는 evaluate_symmetric
    # 의 미러 가설이 위/아래까지 같이 뒤집어 인정한다). 카메라에서 mvp.json 을 그대로 쓰면 180도
    # 회전이 그냥 NG 로 나온다 — --config 로 명시하면 이 자동 선택을 덮어쓴다.
    config_path = args.config or ("config/rtdetr_live.json" if args.source == "camera" else "config/mvp.json")
    config = load_config(ROOT / config_path)
    store = Store(ROOT / args.db, max_frame_gap_ms=config["max_frame_gap_ms"])
    hub = Hub()
    if args.source == "demo":
        config = demo_config(config, args.speed)        # 배속이면 코어 안정화 창도 같이 줄인다
        factory, model = (lambda recipe, cfg: DemoSource(recipe, cfg, fps=args.fps, speed=args.speed)), "demo"
    elif args.source == "jsonl":
        factory, model = (lambda recipe, cfg: JsonlSource(args.jsonl)), f"jsonl:{args.jsonl}"
    else:
        is_rule_based = args.model_type == "rule_based"
        need = ("cv2",) if (args.no_model or is_rule_based) else ("cv2", "ultralytics")
        missing = [m for m in need if importlib.util.find_spec(m) is None]
        if missing:
            raise SystemExit(f"--source camera 에 필요한 패키지가 없습니다: {', '.join(missing)}  →  pip install -r requirements.txt")
        weights = None if (args.no_model or is_rule_based) else (args.weights or DEFAULT_WEIGHTS.get(args.model_type))
        if weights is None and not args.no_model and not is_rule_based:
            raise SystemExit(f"--model-type {args.model_type}는 저장소에 기본 가중치가 없습니다. --weights 로 지정하세요.")
        if weights and not (ROOT / weights).exists() and not Path(weights).exists():
            raise SystemExit(f"가중치 파일이 없습니다: {weights}  (모델 담당에게 받아 model/ 에 두고 --weights 로 지정. "
                             f"카메라만 먼저 보려면 --no-model)")
        size = tuple(int(x) for x in args.camera_size.lower().split("x"))
        if args.video and not Path(args.video).exists():
            raise SystemExit(f"영상 파일이 없습니다: {args.video}")
        mapping_path = Path(args.class_map) if args.class_map else ROOT / "config/class_mapping.json"
        net, model_label = None, "camera-only"
        if weights:                                     # 모델을 여기서 한 번 연다 — 못 열면 화면을 띄우기 전에 멈춘다
            if preloaded is not None:
                net = preloaded
            else:
                from ultralytics import RTDETR, YOLO
                net = RTDETR(weights) if args.model_type == "rtdetr" else YOLO(weights)
            model_label = f"{args.model_type}:{Path(weights).name}"
            print(f"[model] {model_label}  (매핑: {mapping_path.relative_to(ROOT) if mapping_path.is_relative_to(ROOT) else mapping_path}, yolo-obb 전용)")
        elif is_rule_based:
            model_label = "rule_based (모델 없음, classical CV)"
            print(f"[model] {model_label}")
        factory = lambda recipe, cfg: CameraSource(args.camera, weights, frame_size=size, conf=args.conf,
                                                    imgsz=args.imgsz, mapping_path=mapping_path, model=net,
                                                    video=args.video, video_end=args.video_end,
                                                    model_type=args.model_type, flip_horizontal=args.flip_horizontal,
                                                    flip_vertical=args.flip_vertical)
        model = weights or ("rule_based" if is_rule_based else "camera-only")
    recipe_dirs, recipe, link = [ROOT / args.recipe_dir], args.recipe, None
    if getattr(args, "mes_broker", None):            # MES 연동: 작업지시가 레시피·수량을 정한다 (docs/mes_mqtt.md)
        from web.mes_link import MesLink, PahoTransport, parse_broker
        host, port = parse_broker(args.mes_broker)
        mes_dir = ROOT / args.mes_dir
        link = MesLink(args.station, mes_dir / "recipes", mes_dir / "mes_link.db", transport=PahoTransport(host, port),
                       prefix=args.mes_prefix, broker=f"{host}:{port}")
        recipe_dirs.append(mes_dir / "recipes")
        wo = link.work_order                         # 재시작: 진행 중이던 작업지시의 레시피로 시작
        if wo and wo["status"] == "IN_PROGRESS" and (mes_dir / "recipes" / f"{wo['recipe_id']}.json").exists():
            recipe = wo["recipe_id"]
    pipeline = Pipeline(config, recipe_dirs, store, factory, recipe, hub.publish, model_file=model)
    pipeline.model_label = model_label if args.source == "camera" else model   # 진단 탭 · 사이드바에 보이는 모델 이름
    if link is not None:
        pipeline.attach_mes(link)
    return create_app(pipeline, store, hub), pipeline, store, hub


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=["demo", "jsonl", "camera"], default="demo")
    p.add_argument("--recipe", default="recipe_1")
    p.add_argument("--config", default=None,
                   help="판정 설정. 생략하면 --source별 기본값: demo/jsonl은 데모 시나리오가 맞춰 짜인 "
                        "config/mvp.json(±15°, 위쪽만, 좌우뒤집힘 불허), camera는 config/rtdetr_live.json"
                        "(각도 89.9°, 좌우뒤집힘·180도 전체회전 허용, 부품 아래쪽은 여전히 NG)")
    p.add_argument("--recipe-dir", default="config/recipes", help="레시피 JSON 폴더. 서버를 켠 뒤 넣은 파일도 레시피 탭을 열면 잡힌다")
    p.add_argument("--db", default="data/pokayoke.db")
    p.add_argument("--jsonl", default="detections.jsonl")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--video", default=None, help="웹캠 대신 녹화한 조립 영상 파일 (원래 속도로 재생, 판정은 카메라와 같음). --source camera 로 간주")
    p.add_argument("--video-end", choices=["hold", "loop", "stop"], default="hold",
                   help="영상이 끝나면: hold 마지막 장면 유지(기본 — PASS 와 [작업 완료] 가 남는다) · loop 처음부터 · stop 종료. "
                        "[새 작업]·[작업 완료] 는 언제나 처음부터 다시 재생")
    p.add_argument("--weights", default=None, help="검출 가중치 .pt. 생략하면 --model-type별 기본 경로(web/source.py의 DEFAULT_WEIGHTS)")
    p.add_argument("--model-type", choices=["rtdetr", "yolo", "yolo-obb", "rule_based"], default="rtdetr",
                   help="검출 방식 (scripts/live_inspection.py와 동일). rule_based는 모델·가중치가 필요 없음")
    p.add_argument("--class-map", default=None, help="클래스 이름 매핑 JSON (yolo-obb 전용). 기본: config/class_mapping.json")
    p.add_argument("--camera-size", default="1280x720", help="캡처 해상도 WxH. 카메라가 다른 값을 주면 실제 값으로 바꿔 쓴다")
    p.add_argument("--flip-horizontal", action="store_true",
                   help="카메라 영상이 좌우반전(미러)돼서 나올 때 되돌린다 (카메라/드라이버가 원래 뒤집어서 주는 경우용)")
    p.add_argument("--flip-vertical", action="store_true",
                   help="카메라가 상하 거꾸로(180도 돌려 설치 등) 영상을 줄 때 되돌린다. --flip-horizontal과 "
                        "같이 켜면 상하좌우 모두 뒤집힘")
    p.add_argument("--conf", type=float, default=0.25, help="모델 후보 임계 (판정 임계 0.5 는 config)")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--no-model", action="store_true", help="가중치 없이 카메라 영상만 (구도·해상도 확인용). 판정은 전부 보류")
    p.add_argument("--fps", type=float, default=10.0)
    p.add_argument("--speed", type=float, default=1.0, help="데모 시나리오 배속 (안정화 창도 같이 나눔, demo 전용)")
    p.add_argument("--mes-broker", default=None, help="MES 연동: MQTT 브로커 주소 (예: localhost:1883). 없으면 연동 없이 지금처럼")
    p.add_argument("--station", default="VIS-01", help="이 검사대의 설비 ID — 토픽 factory/<station>/…")
    p.add_argument("--mes-prefix", default="factory", help="MQTT 토픽 앞부분")
    p.add_argument("--mes-dir", default="data/mes", help="MES 가 내려준 레시피·보낼 목록(outbox) 을 두는 곳")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)
    if args.video:                                   # 영상 파일 = 카메라 경로를 그대로 쓴다
        args.source = "camera"
    return args


def serve(args, preloaded=None):
    import uvicorn
    app, pipeline, store, hub = build(args, preloaded)
    pipeline.start()
    if pipeline.mes is not None:
        pipeline.mes.start()
        print(f"MES 연동: 브로커 {pipeline.mes.broker} · 설비 {pipeline.mes.station_id} · 토픽 {pipeline.mes.topic('#')}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def main(argv=None):
    serve(parse(argv))


if __name__ == "__main__":
    main()
