"""비전 검사대 ↔ MES (MQTT). 계약은 docs/mes_mqtt.md.

두 층으로 나눈다:
  MesLink        — 판단(작업지시 적용·거절, 수량 세기, outbox, 화면 표시값). 통신 라이브러리를 모른다 → 가짜 전송으로 테스트한다.
  PahoTransport  — paho-mqtt 로 실제 브로커에 붙는 얇은 층 (연결·구독·발행·LWT). pip install paho-mqtt

스레드: paho 네트워크 스레드(메시지 수신) · 보내기 스레드(outbox → 브로커) · 파이프라인 스레드(제품 완료 알림).
상태는 self._lock 하나로, SQLite 는 자기 연결 하나로 (web/store.py 의 DB 와 따로 — 서로 잠그지 않게).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from src.process.recipe import Placement, Recipe

SCHEMA = "pokayoke/1"
ACTIVE, COMPLETED, CANCELLED = "IN_PROGRESS", "COMPLETED", "CANCELLED"


def local_iso() -> str:
    """시간대가 붙은 지금 시각 (예: 2026-09-28T09:12:03+09:00). MES 가 KST/UTC 를 헷갈리지 않게."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Transport(Protocol):
    def start(self, link: "MesLink") -> None: ...
    def stop(self) -> None: ...
    def is_connected(self) -> bool: ...
    def subscribe(self, topic: str, qos: int) -> None: ...
    def publish(self, topic: str, payload: str, qos: int, retain: bool, wait: bool = True) -> bool: ...   # 브로커가 받았다고 답하면 True


class MesLink:
    def __init__(self, station_id: str, recipe_dir: str | Path, db_path: str | Path, transport: Transport | None = None,
                 prefix: str = "factory", on_work_order: Callable[[dict | None], None] | None = None,
                 clock: Callable[[], str] = local_iso, broker: str = ""):
        self.station_id, self.prefix, self.broker = station_id, prefix, broker
        self.recipe_dir = Path(recipe_dir)
        self.recipe_dir.mkdir(parents=True, exist_ok=True)
        self.transport = transport
        self.on_work_order = on_work_order          # 파이프라인이 꽂는다: 작업지시 적용(dict) / 취소(None)
        self.clock = clock
        self.connected = False
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._sender: threading.Thread | None = None
        path = Path(db_path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS outbox (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, topic TEXT NOT NULL,
              payload TEXT NOT NULL, created_at TEXT NOT NULL, sent_at TEXT, attempts INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS work_order (
              id INTEGER PRIMARY KEY CHECK (id = 1), body TEXT NOT NULL);
        """)
        row = self._db.execute("SELECT body FROM work_order WHERE id=1").fetchone()
        self.work_order: dict | None = json.loads(row[0]) if row else None     # 재시작해도 진행 수량 유지

    # ── 토픽 ──
    def topic(self, kind: str) -> str:
        return f"{self.prefix}/{self.station_id}/{kind}"

    # ── 시작 · 끝 ──
    def start(self) -> None:
        if self.transport is not None:
            self.transport.start(self)
        self._sender = threading.Thread(target=self._send_loop, name="mes-sender", daemon=True)
        self._sender.start()

    def stop(self) -> None:
        self._stop.set(); self._wake.set()
        if self.transport is not None:
            self.transport.stop()

    def close(self) -> None:
        """stop() 에 더해 SQLite 파일을 놓는다 — 윈도우는 열린 파일을 못 지워서, 테스트의 임시 폴더 정리가 실패했다 (09-28 노트북)."""
        self.stop()
        if self._sender is not None:
            self._sender.join(timeout=2)
        with self._lock:
            self._db.close()

    # ── 전송층이 부르는 것 ──
    def on_connected(self) -> None:
        self.connected = True
        self.transport.subscribe(self.topic("workorder"), 1)
        # 이 함수는 paho 네트워크 스레드 안에서 불린다 — 여기서 PUBACK 을 기다리면 그 스레드가 막혀 영영 안 온다 (wait=False)
        self.transport.publish(self.topic("status"), json.dumps(
            {"schema": SCHEMA, "station_id": self.station_id, "state": "online", "occurred_at": self.clock()}), 1, True, wait=False)
        self._wake.set()                            # 끊긴 동안 쌓인 것을 바로 보낸다

    def on_disconnected(self) -> None:
        self.connected = False

    def on_message(self, topic: str, payload: bytes) -> None:
        if topic != self.topic("workorder"):
            return
        if not payload:                             # retained 비움 = 작업지시 없음
            self._clear()
            return
        wo = None
        try:
            wo = json.loads(payload.decode("utf-8"))
            recipe = wo["recipe"]
            work_order_id, quantity = str(wo["work_order_id"]), int(wo["quantity"])
            recipe_id, version = str(recipe["recipe_id"]), int(recipe["version"])
            placements = recipe["placements"]
        except (ValueError, KeyError, TypeError) as error:
            self._ack("REJECTED", str(wo.get("work_order_id", "?")) if isinstance(wo, dict) else "?",
                      reason=f"BAD_MESSAGE: {type(error).__name__}: {error}")
            return
        nxt = [{"work_order_id": str(n.get("work_order_id")), "recipe_id": str(n.get("recipe_id")), "quantity": int(n.get("quantity", 0))}
               for n in (wo.get("next") or []) if isinstance(n, dict)]   # MES 대기열 (보여 주기용, 없어도 됨)
        with self._lock:
            cur = self.work_order
            if cur and cur["work_order_id"] == work_order_id:
                cur["next"] = nxt                   # 같은 작업지시 재전달 — 진행 수량 그대로, 대기열 표시만 새로
                self._save()
                return
            if cur and cur["status"] == ACTIVE:
                self._ack("REJECTED", work_order_id, reason=f"BUSY: {cur['work_order_id']} 진행 중 ({cur['done']}/{cur['quantity']})")
                return
        try:                                        # 검사대의 레시피 규칙(H1~H4, 부품 종류) 로 먼저 검사
            Recipe(recipe_id, tuple(Placement(**p) for p in placements))
            if quantity < 1:
                raise ValueError("quantity must be >= 1")
        except (ValueError, TypeError) as error:
            self._ack("REJECTED", work_order_id, reason=f"INVALID_RECIPE: {error}")
            return
        (self.recipe_dir / f"{recipe_id}.json").write_text(json.dumps(
            {"recipe_id": recipe_id, "version": version, "placements": placements, "source": "MES",
             "work_order_id": work_order_id}, ensure_ascii=False, indent=1), encoding="utf-8")
        with self._lock:
            before = self.work_order["status"] if self.work_order else None   # 바뀌기 전: 없음 · COMPLETED · CANCELLED
            self.work_order = {"work_order_id": work_order_id, "recipe_id": recipe_id, "recipe_version": version,
                               "quantity": quantity, "done": 0, "status": ACTIVE, "accepted_at": self.clock(), "next": nxt}
            self._save()
            self._ack("ACCEPTED", work_order_id)
            wo_view = dict(self.work_order, replaced_status=before)
        if self.on_work_order:
            self.on_work_order(wo_view)

    def _clear(self) -> None:
        with self._lock:
            cur = self.work_order
            if cur is None or cur["status"] != ACTIVE:
                return                              # 이미 끝난 작업지시를 MES 가 정리한 것 — 할 일 없음
            cur["status"] = CANCELLED
            self._save()
            self._ack("CANCELLED", cur["work_order_id"])
        if self.on_work_order:
            self.on_work_order(None)

    # ── 파이프라인이 부르는 것 ──
    def can_complete(self) -> tuple[bool, str]:
        with self._lock:
            wo = self.work_order
            if wo is None or wo["status"] != ACTIVE:
                return False, "작업지시가 없습니다 — MES 에서 작업지시가 오면 시작합니다"
            return True, ""

    def product_completed(self, summary: dict, ng_codes: list[str]) -> dict | None:
        """[작업 완료] 로 제품이 COMPLETED 로 닫힌 직후 (파이프라인 스레드). result 를 outbox 에 쓰고 수량을 센다."""
        with self._lock:
            wo = self.work_order
            if wo is None or wo["status"] != ACTIVE:
                return None
            wo["done"] += 1
            result = {"schema": SCHEMA, "event_id": str(uuid.uuid4()), "station_id": self.station_id,
                      "work_order_id": wo["work_order_id"], "product_seq": wo["done"],
                      "local_product_id": summary.get("product_id"),
                      "recipe_id": wo["recipe_id"], "recipe_version": wo["recipe_version"],
                      "first_pass": bool(summary.get("first_pass")), "ng_count": summary.get("ng_count", 0),
                      "material_ng_count": summary.get("material_ng_count", 0), "hold_count": summary.get("hold_count", 0),
                      "ng_codes": list(ng_codes), "cycle_ms": summary.get("cycle_ms"),
                      "materials_ms": summary.get("materials_ms"), "assembly_ms": summary.get("assembly_ms"),
                      "occurred_at": self.clock()}
            self._enqueue(self.topic("result"), result)
            if wo["done"] >= wo["quantity"]:
                wo["status"] = COMPLETED
                self._ack("COMPLETED", wo["work_order_id"])
            self._save()
        self._wake.set()
        return result

    def view(self) -> dict:
        """화면 payload 의 "mes" (헤더의 작업지시 줄, 대기 카드)."""
        with self._lock:
            pending = self._db.execute("SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL").fetchone()[0]
            return {"enabled": True, "connected": self.connected, "station_id": self.station_id, "broker": self.broker,
                    "work_order": dict(self.work_order) if self.work_order else None, "pending": pending}

    # ── outbox ──
    def _ack(self, kind: str, work_order_id: str, reason: str | None = None) -> None:
        wo = self.work_order if self.work_order and self.work_order["work_order_id"] == work_order_id else None
        self._enqueue(self.topic("ack"), {"schema": SCHEMA, "event_id": str(uuid.uuid4()), "station_id": self.station_id,
                                          "type": kind, "work_order_id": work_order_id,
                                          "done": wo["done"] if wo else None, "quantity": wo["quantity"] if wo else None,
                                          "reason": reason, "occurred_at": self.clock()})
        self._wake.set()

    def _enqueue(self, topic: str, message: dict) -> None:
        with self._lock:
            self._db.execute("INSERT INTO outbox(event_id, topic, payload, created_at) VALUES (?,?,?,?)",
                             (message["event_id"], topic, json.dumps(message, ensure_ascii=False), self.clock()))

    def _save(self) -> None:
        self._db.execute("INSERT INTO work_order(id, body) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                         (json.dumps(self.work_order, ensure_ascii=False),))

    def flush(self, limit: int = 100) -> int:
        """보낼 것을 만든 순서대로. 브로커가 받았다고 답한 것만 sent 로 표시 — 하나라도 실패하면 거기서 멈춘다 (순서 유지)."""
        if self.transport is None or not self.transport.is_connected():
            return 0
        with self._lock:
            rows = self._db.execute("SELECT seq, topic, payload FROM outbox WHERE sent_at IS NULL ORDER BY seq LIMIT ?",
                                    (limit,)).fetchall()
        sent = 0
        for seq, topic, payload in rows:
            ok = self.transport.publish(topic, payload, 1, False)
            with self._lock:
                self._db.execute("UPDATE outbox SET attempts=attempts+1" + (", sent_at=?" if ok else "") + " WHERE seq=?",
                                 ((self.clock(), seq) if ok else (seq,)))
            if not ok:
                break
            sent += 1
        return sent

    def _send_loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=2.0)
            self._wake.clear()
            try:
                self.flush()
            except Exception:                       # 보내기 실패로 검사가 멈추면 안 된다. 다음 주기에 다시
                pass


class PahoTransport:
    """paho-mqtt(2.x) 로 브로커에 붙는다. LWT·재연결·세션 유지만 여기서 정한다."""

    def __init__(self, host: str, port: int = 1883, client_id: str | None = None, keepalive: int = 30):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as error:
            raise SystemExit("MES 연동에는 paho-mqtt 가 필요합니다: pip install paho-mqtt") from error
        self._mqtt = mqtt
        self.host, self.port, self.keepalive = host, port, keepalive
        self.client_id = client_id
        self.client = None
        self._connected = False

    def start(self, link: MesLink) -> None:
        mqtt = self._mqtt
        # 고정 client id + clean_session=False: 끊긴 사이 MES 가 보낸 QoS1 메시지(작업지시 비움 등)를 재연결 때 받는다
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id or f"station-{link.station_id}",
                                  clean_session=False)
        self.client.will_set(link.topic("status"), json.dumps({"schema": SCHEMA, "station_id": link.station_id, "state": "offline"}),
                             qos=1, retain=True)
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)

        def on_connect(client, userdata, flags, reason_code, properties):
            if not reason_code.is_failure:
                self._connected = True
                link.on_connected()

        def on_disconnect(client, userdata, flags, reason_code, properties):
            self._connected = False
            link.on_disconnected()

        def on_message(client, userdata, msg):
            link.on_message(msg.topic, msg.payload)

        self.client.on_connect, self.client.on_disconnect, self.client.on_message = on_connect, on_disconnect, on_message
        self.client.connect_async(self.host, self.port, keepalive=self.keepalive)
        self.client.loop_start()                    # 네트워크 스레드 — 끊기면 알아서 다시 붙는다

    def stop(self) -> None:
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()

    def is_connected(self) -> bool:
        return self._connected

    def subscribe(self, topic: str, qos: int) -> None:
        self.client.subscribe(topic, qos=qos)

    def publish(self, topic: str, payload: str, qos: int, retain: bool, wait: bool = True) -> bool:
        try:
            info = self.client.publish(topic, payload, qos=qos, retain=retain)
            if not wait:
                return info.rc == self._mqtt.MQTT_ERR_SUCCESS
            info.wait_for_publish(timeout=5)        # QoS1: 브로커의 PUBACK 까지 기다린다 (보내기 스레드에서만)
            return info.is_published()
        except (RuntimeError, ValueError):          # 연결 없음 등 — outbox 에 남아 다음에 다시
            return False


def parse_broker(value: str) -> tuple[str, int]:
    """"localhost:1883" / "mqtt://host:1883" / "host" → (host, port)."""
    value = value.split("://", 1)[-1]
    host, _, port = value.partition(":")
    return host or "localhost", int(port or 1883)
