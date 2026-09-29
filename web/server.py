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
from web.pipeline import Pipeline, list_recipes
from web.source import CameraSource, DemoSource, JsonlSource, demo_config
from web.store import Store

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).with_name("static")


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
        return FileResponse(STATIC / "index.html")

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
        return JSONResponse({"current": pipeline.recipe.recipe_id, "recipes": list_recipes(pipeline.recipe_dir)})

    async def select_recipe(request):
        rid = request.path_params["recipe_id"]
        try:
            pipeline.select_recipe(rid)
        except KeyError:
            return JSONResponse({"ok": False, "reason": f"unknown recipe {rid}"}, 404)
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
        Mount("/static", StaticFiles(directory=str(STATIC)), name="static"),
    ])


def build(args) -> tuple[Starlette, Pipeline, Store, Hub]:
    config = load_config(ROOT / args.config)
    store = Store(ROOT / args.db, max_frame_gap_ms=config["max_frame_gap_ms"])
    hub = Hub()
    if args.source == "demo":
        config = demo_config(config, args.speed)        # 배속이면 코어 안정화 창도 같이 줄인다
        factory, model = (lambda recipe, cfg: DemoSource(recipe, cfg, fps=args.fps, speed=args.speed)), "demo"
    elif args.source == "jsonl":
        factory, model = (lambda recipe, cfg: JsonlSource(args.jsonl)), f"jsonl:{args.jsonl}"
    else:
        factory, model = (lambda recipe, cfg: CameraSource(args.camera, args.weights)), args.weights
    pipeline = Pipeline(config, ROOT / "config/recipes", store, factory, args.recipe, hub.publish, model_file=model)
    return create_app(pipeline, store, hub), pipeline, store, hub


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=["demo", "jsonl", "camera"], default="demo")
    p.add_argument("--recipe", default="recipe_1")
    p.add_argument("--config", default="config/mvp.json")
    p.add_argument("--db", default="data/pokayoke.db")
    p.add_argument("--jsonl", default="detections.jsonl")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--weights", default="model/yolo_obb_parts.pt")
    p.add_argument("--fps", type=float, default=10.0)
    p.add_argument("--speed", type=float, default=1.0, help="데모 시나리오 배속 (안정화 창도 같이 나눔, demo 전용)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    return p.parse_args(argv)


def main(argv=None):
    import uvicorn
    args = parse(argv)
    app, pipeline, store, hub = build(args)
    pipeline.start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
