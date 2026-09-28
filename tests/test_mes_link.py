"""검사대 ↔ MES (web/mes_link.py) — 브로커·paho 없이 가짜 전송으로. 계약은 docs/mes_mqtt.md."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from web.mes_link import MesLink, parse_broker

ROOT = Path(__file__).resolve().parents[1]
RECIPE = {"recipe_id": "recipe_2", "version": 3,
          "placements": [{"mother_hole": 1, "bolt": "bolt_1", "part": "part_2hole"},
                         {"mother_hole": 3, "bolt": "bolt_2", "part": "part_3hole"}]}


def wo_msg(wid="WO-1", qty=2, recipe=RECIPE, next_=None):
    msg = {"schema": "pokayoke/1", "work_order_id": wid, "station_id": "VIS-01", "recipe": recipe, "quantity": qty}
    if next_ is not None:
        msg["next"] = next_
    return json.dumps(msg).encode()


class FakeTransport:
    """브로커 흉내: 발행을 기록하고, fail=True 면 PUBACK 이 안 온 것처럼 False."""
    def __init__(self):
        self.published, self.subscribed, self.connected, self.fail = [], [], True, False

    def start(self, link): pass
    def stop(self): pass
    def is_connected(self): return self.connected
    def subscribe(self, topic, qos): self.subscribed.append((topic, qos))

    def publish(self, topic, payload, qos, retain, wait=True):
        if self.fail or not self.connected:
            return False
        self.published.append((topic, json.loads(payload), qos, retain))
        return True

    def of(self, kind):
        return [m for t, m, *_ in self.published if t.endswith("/" + kind)]


class MesLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.dir = Path(self.tmp.name)
        self.t = FakeTransport(); self.applied = []; self.links = []
        self.link = self.make()

    def tearDown(self):
        for link in self.links:                  # 윈도우: 열린 SQLite 를 닫아야 임시 폴더를 지운다
            link.close()
        self.tmp.cleanup()

    def make(self):
        link = MesLink("VIS-01", self.dir / "recipes", self.dir / "mes.db", transport=self.t,
                       on_work_order=self.applied.append, clock=lambda: "2026-09-28T09:00:00+09:00")
        self.links.append(link)
        return link

    def send(self, payload, link=None):
        (link or self.link).on_message("factory/VIS-01/workorder", payload)

    def done(self, n=1, link=None):
        for i in range(n):
            (link or self.link).product_completed({"product_id": 100 + i, "first_pass": 1, "ng_count": 0, "cycle_ms": 40000},
                                                  [] if i else ["WRONG_BOLT:H1"])

    def test_connect_subscribes_and_announces_online(self):
        self.link.on_connected()
        self.assertEqual(self.t.subscribed, [("factory/VIS-01/workorder", 1)])
        topic, msg, qos, retain = self.t.published[0]
        self.assertEqual((topic, msg["state"], qos, retain), ("factory/VIS-01/status", "online", 1, True))

    def test_work_order_applies_recipe_and_acks(self):
        self.send(wo_msg())
        self.assertEqual(self.applied[-1]["recipe_id"], "recipe_2")
        saved = json.loads((self.dir / "recipes" / "recipe_2.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["version"], saved["source"]), (3, "MES"))       # 파이프라인이 이 파일로 레시피를 연다
        self.link.flush()
        self.assertEqual([a["type"] for a in self.t.of("ack")], ["ACCEPTED"])
        self.assertTrue(self.link.can_complete()[0])

    def test_redelivered_same_work_order_keeps_progress(self):
        self.send(wo_msg(qty=3)); self.done(2)
        self.send(wo_msg(qty=3))                                                # 재연결 때 retained 가 다시 옴
        self.assertEqual(len(self.applied), 1)
        self.assertEqual(self.link.work_order["done"], 2)

    def test_counts_results_and_completes_at_quantity(self):
        self.send(wo_msg(qty=2)); self.done(2); self.link.flush()
        results = self.t.of("result")
        self.assertEqual([r["product_seq"] for r in results], [1, 2])
        self.assertEqual(results[0]["ng_codes"], ["WRONG_BOLT:H1"])
        self.assertEqual((results[0]["recipe_id"], results[0]["recipe_version"]), ("recipe_2", 3))
        self.assertEqual(len({r["event_id"] for r in results}), 2)
        self.assertEqual([a["type"] for a in self.t.of("ack")], ["ACCEPTED", "COMPLETED"])
        self.assertEqual(self.link.work_order["status"], "COMPLETED")
        self.assertFalse(self.link.can_complete()[0])                            # 다 만들면 [작업 완료] 막힘
        self.assertIsNone(self.link.product_completed({}, []))                   # 더 세지 않는다

    def test_busy_invalid_and_bad_messages_are_rejected(self):
        self.send(wo_msg("WO-1")); self.send(wo_msg("WO-2"))
        bad = dict(RECIPE, placements=[{"mother_hole": 5, "bolt": "bolt_1", "part": "part_2hole"}])
        self.link.work_order["status"] = "COMPLETED"
        self.send(wo_msg("WO-3", recipe=bad)); self.send(b"{not json")
        self.link.flush()
        acks = self.t.of("ack")
        self.assertEqual([a["type"] for a in acks], ["ACCEPTED", "REJECTED", "REJECTED", "REJECTED"])
        self.assertTrue(acks[1]["reason"].startswith("BUSY"))
        self.assertTrue(acks[2]["reason"].startswith("INVALID_RECIPE"))
        self.assertTrue(acks[3]["reason"].startswith("BAD_MESSAGE"))
        self.assertEqual(len(self.applied), 1)

    def test_empty_retained_cancels_only_an_active_order(self):
        self.send(wo_msg()); self.send(b"")
        self.assertIsNone(self.applied[-1]); self.assertEqual(self.link.work_order["status"], "CANCELLED")
        self.send(wo_msg("WO-2", qty=1)); self.done(1); n = len(self.applied)
        self.send(b"")                                                          # 완료 뒤 MES 가 정리 — 그대로
        self.assertEqual((len(self.applied), self.link.work_order["status"]), (n, "COMPLETED"))

    def test_outbox_survives_disconnect_and_keeps_order(self):
        self.send(wo_msg(qty=3)); self.t.connected = False; self.done(2)
        self.assertEqual(self.link.flush(), 0)
        self.assertEqual(self.link.view()["pending"], 3)                        # ACCEPTED + result 2
        self.t.connected = True; self.t.fail = True
        self.assertEqual(self.link.flush(), 0)                                  # PUBACK 없음 → 첫 건에서 멈춤 (순서 유지)
        self.t.fail = False
        self.assertEqual(self.link.flush(), 3)
        kinds = [t.rsplit("/", 1)[1] for t, *_ in self.t.published]
        self.assertEqual(kinds, ["ack", "result", "result"])
        self.assertEqual(self.link.view()["pending"], 0)

    def test_restart_restores_work_order_and_unsent_events(self):
        self.send(wo_msg(qty=5)); self.t.connected = False; self.done(2)
        again = self.make()                                                     # 검사대 재시작
        self.assertEqual((again.work_order["work_order_id"], again.work_order["done"]), ("WO-1", 2))
        self.send(wo_msg(qty=5), link=again)                                    # retained 재전달 → 무시
        self.assertEqual(again.work_order["done"], 2)
        self.t.connected = True
        self.assertEqual(again.flush(), 3)

    def test_queue_from_mes_is_shown_and_refreshed_without_touching_progress(self):
        q1 = [{"work_order_id": "WO-2", "recipe_id": "recipe_2", "quantity": 3}]
        self.send(wo_msg(qty=2, next_=q1))
        self.assertEqual(self.applied[-1]["replaced_status"], None)            # 앞에 작업지시 없었음
        self.assertEqual(self.link.view()["work_order"]["next"], q1)
        self.done(1)
        q2 = q1 + [{"work_order_id": "WO-3", "recipe_id": "recipe_1", "quantity": 1}]
        self.send(wo_msg(qty=2, next_=q2))                                      # 같은 작업지시 재전달 — 대기열만 바뀜
        wo = self.link.view()["work_order"]
        self.assertEqual((wo["done"], len(wo["next"])), (1, 2))
        self.assertEqual(len(self.applied), 1)                                   # 다시 적용하지 않는다
        self.done(1)                                                             # 수량 채움 → COMPLETED
        self.send(wo_msg(wid="WO-2", qty=3, next_=[]))                           # MES 가 다음 줄을 보냄
        self.assertEqual(self.applied[-1]["work_order_id"], "WO-2")
        self.assertEqual(self.applied[-1]["replaced_status"], "COMPLETED")

    def test_parse_broker(self):
        self.assertEqual(parse_broker("localhost:1883"), ("localhost", 1883))
        self.assertEqual(parse_broker("mqtt://10.0.0.5"), ("10.0.0.5", 1883))


class PipelineWithMesTests(unittest.TestCase):
    """서버 전체 (데모 소스) + 가짜 전송: 작업지시 → 레시피 바뀜 → 드롭다운 잠김 → [작업 완료] 수량."""

    def setUp(self):
        try:
            from starlette.testclient import TestClient
            from web.server import build, parse
        except (ImportError, RuntimeError):      # starlette 없음 · testclient 가 요구하는 httpx 없음 (노트북 환경)
            self.skipTest("starlette testclient not available")
        self.tmp = tempfile.TemporaryDirectory(); d = Path(self.tmp.name)
        args = parse(["--db", str(d / "t.db"), "--fps", "60", "--speed", "4"])
        self.app, self.pipeline, self.store, self.hub = build(args)
        self.t = FakeTransport()
        self.link = MesLink("VIS-01", d / "recipes", d / "mes.db", transport=self.t)
        self.pipeline.recipe_dirs.append(d / "recipes")
        self.pipeline.attach_mes(self.link)
        self.client = TestClient(self.app); self.client.__enter__()
        self.pipeline.start()

    def tearDown(self):
        self.client.__exit__(None, None, None); self.link.close(); self.store.close(); self.tmp.cleanup()     # 서버 종료가 pipeline.stop() 을 부른다

    def wait(self, pred, seconds=20):
        t0 = time.time()
        while time.time() - t0 < seconds:
            s = self.client.get("/api/state").json()
            if pred(s):
                return s
            time.sleep(0.05)
        self.fail(f"timeout; last state {s.get('phase')} {s.get('status')} mes={s.get('mes')}")

    def test_work_order_drives_recipe_and_counts(self):
        s = self.wait(lambda s: s.get("mes") is not None)
        self.assertIsNone(s["mes"]["work_order"])
        self.assertEqual(self.client.post("/api/complete").status_code, 409)                  # 작업지시 없음
        self.link.on_message("factory/VIS-01/workorder", wo_msg(qty=1, recipe=dict(RECIPE, recipe_id="recipe_3")))
        s = self.wait(lambda s: s["recipe"]["recipe_id"] == "recipe_3")
        self.assertEqual(s["recipe"]["source"], "MES")
        self.assertEqual(self.client.post("/api/recipe/recipe_1").status_code, 409)           # 드롭다운 잠김
        self.wait(lambda s: s["phase"] == "ASSEMBLING" and s["status"] == "PASS" and s["stable"], seconds=30)
        r = self.client.post("/api/complete")
        self.assertEqual(r.status_code, 200, r.text)
        s = self.wait(lambda s: s["mes"]["work_order"]["status"] == "COMPLETED")
        self.assertEqual(s["mes"]["work_order"]["done"], 1)
        self.link.flush()
        result = self.t.of("result")[0]
        self.assertEqual((result["work_order_id"], result["product_seq"], result["recipe_id"]), ("WO-1", 1, "recipe_3"))
        self.assertTrue(any(c.startswith("WRONG_") for c in result["ng_codes"]), result["ng_codes"])   # 데모 시나리오의 오조립 이력
        self.assertFalse(result["first_pass"])
        # MES 대기열의 다음 줄이 오면 바로 그 레시피로 — 기다리던 빈 제품은 이력에 '중단' 으로 남지 않는다
        self.link.on_message("factory/VIS-01/workorder", wo_msg(wid="WO-2", qty=2, recipe=dict(RECIPE, recipe_id="recipe_2")))
        s = self.wait(lambda s: s["recipe"]["recipe_id"] == "recipe_2" and s["mes"]["work_order"]["work_order_id"] == "WO-2")
        self.assertEqual(s["phase"], "CHECK_MATERIALS")
        results = [h["result"] for h in self.store.history()]
        self.assertEqual(results, ["COMPLETED"], results)


if __name__ == "__main__":
    unittest.main()
