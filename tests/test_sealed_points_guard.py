"""封批后温度点禁改（甲路径）三条红线测。

夹具（本机文件库 fixtures/）：
- batches.json 的 TB-CK-HD-01-003：已封批批次遭封批后硬改回写，
  正式表 4 点（含 2 个越带影子点）vs 封批快照 2 点；
- seals.json：两个已封批批次的生效快照（manifest 含封批时点列）；
- spectrum.json：封批当下导出的温谱（点数 2、校验和按封批点列计算）。

裁决口径（记入封批温度点纪要并当班封死）：
甲路径 —— 封批代已生效则探头挂接温度点正式表零改并拒写；
偏离已封纪要记温度点偏航并拒写；不采用乙路径影子草案，两套口径不混用。
"""
import json
import threading

import pytest
from fastapi.testclient import TestClient

from app import app
from db import init_db

SEALED_CODE = "TB-CK-HD-01-003"  # 夹具：封批后仍被硬改温度点的批次
SEALED_EXPORT_REF = "SP-TB-CK-HD-01-003-G2"


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "t.db")
    init_db()
    yield


def _auth(c: TestClient, user="admin") -> dict:
    tok = c.post(
        "/api/login", json={"username": user, "password": "123456"}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _fixture_batch(c: TestClient, h: dict) -> dict:
    items = c.get("/api/batches", headers=h).json()["items"]
    return next(b for b in items if b["batch_code"] == SEALED_CODE)


def test_sealed_official_points_rewrite_rejected():
    """红①：已封批正式挂接点还能被改写。

    甲路径：封批代已生效，探头回写正式温度点必须零改并拒写，
    且偏离已封纪要须记温度点偏航；纪要当班封死（locked）。
    """
    c = TestClient(app)
    h = _auth(c)
    fx = _fixture_batch(c, h)
    bid, pid = fx["id"], fx["probe_id"]
    before = c.get(f"/api/batches/{bid}", headers=h).json()["batch"]["temp_points"]
    r = c.post(
        f"/api/probes/{pid}/writeback",
        headers=h,
        json={"batch_id": bid, "points": [{"t": "23:00", "c": -18.9}]},
    )
    assert r.status_code == 409, "已封批回写未被拒写"
    assert "已封批" in r.json()["detail"]
    after = c.get(f"/api/batches/{bid}", headers=h).json()["batch"]["temp_points"]
    assert after == before, "已封批正式温度点被改写"
    devs = c.get("/api/seal-deviations", headers=h).json()["items"]
    assert any(
        d["batch_id"] == bid and d["source"] == "回写拒写" for d in devs
    ), "偏离已封纪要未记温度点偏航"
    memos = c.get("/api/seal-memos", headers=h).json()["items"]
    memo = next(m for m in memos if m["batch_id"] == bid)
    assert memo["policy_path"] == "甲", "封批温度点纪要未记甲路径"
    assert memo["locked"] == 1, "纪要未当班封死"


def test_unpromoted_postseal_points_kept_out_of_spectrum():
    """红②：封批后混入的影子点未晋升却进了正式温谱。

    正式表与正式温谱只认封批快照点列；未晋升影子点必须隔离进偏航记录，
    不得混入批次详情、温谱导出任何一处正式面。
    """
    c = TestClient(app)
    h = _auth(c)
    fx = _fixture_batch(c, h)
    bid = fx["id"]
    seals = c.get("/api/seals", headers=h).json()["items"]
    snap = next(s for s in seals if s["batch_id"] == bid)
    manifest = json.loads(snap["manifest"])
    assert manifest["point_count"] == 2, "夹具快照应为封批时 2 点"
    batch = c.get(f"/api/batches/{bid}", headers=h).json()["batch"]
    assert batch["temp_points"] == manifest["points"], "影子点仍挂在正式表"
    assert batch["point_integrity"] == "一致", "正式点列与封批快照不一致"
    exp = c.get(f"/api/spectrum/{SEALED_EXPORT_REF}", headers=h).json()
    assert exp["point_count"] == 2
    assert exp["temp_points"] == manifest["points"], "未晋升影子点混入正式温谱"
    devs = c.get("/api/seal-deviations", headers=h).json()["items"]
    drift = [d for d in devs if d["batch_id"] == bid and d["source"] == "迁移修复"]
    assert drift, "封批后硬改未被记为温度点偏航"
    assert len(json.loads(drift[0]["attempted_points"])) == 4


def test_concurrent_writeback_contention_lock():
    """红③：双人同批改点无锁。

    两人同时改同一已封批批次的挂接温度点须抢批次锁，
    后到会话只记争用痕不写采样点；并发两路打同批改点正式表零改。
    """
    c = TestClient(app)
    h1 = _auth(c, "admin")
    h2 = _auth(c, "ops")
    fx = _fixture_batch(c, h1)
    bid, pid = fx["id"], fx["probe_id"]
    key = f"batch:{bid}"
    held = c.post("/api/locks/acquire", headers=h1, json={"lock_key": key})
    assert held.status_code == 200
    try:
        r = c.post(
            f"/api/probes/{pid}/writeback",
            headers=h2,
            json={"batch_id": bid, "points": [{"t": "23:30", "c": -18.7}]},
        )
        assert r.status_code == 409, "后到会话未被判争用"
        assert "争用" in r.json()["detail"]
    finally:
        c.post("/api/locks/release", headers=h1, json={"lock_key": key})
    cont = c.get("/api/contention", headers=h1).json()["items"]
    assert any(
        x["lock_key"] == key and x["actor"] == "ops" for x in cont
    ), "后到会话未留下争用痕"

    before = c.get(f"/api/batches/{bid}", headers=h1).json()["batch"]["temp_points"]
    barrier = threading.Barrier(2)
    codes = []

    def hit(hdr):
        barrier.wait(timeout=10)
        cc = TestClient(app)
        resp = cc.post(
            f"/api/probes/{pid}/writeback",
            headers=hdr,
            json={"batch_id": bid, "points": [{"t": "23:45", "c": -18.6}]},
        )
        codes.append(resp.status_code)

    t1 = threading.Thread(target=hit, args=(h1,))
    t2 = threading.Thread(target=hit, args=(h2,))
    t1.start()
    t2.start()
    t1.join(30)
    t2.join(30)
    assert sorted(codes) == [409, 409], "并发回写已封批须双双拒写"
    after = c.get(f"/api/batches/{bid}", headers=h1).json()["batch"]["temp_points"]
    assert after == before, "并发下正式温度点被改写"
