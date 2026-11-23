"""探头登记与在线态 + 探头回写挂接批次温度点（封批后甲路径零改）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, record_point_deviation, write_audit
from locks import release, require_lock
from models import ProbeIn, ProbeWritebackIn
from validators import summarize_points, validate_probe_online, validate_temp_point

router = APIRouter(tags=["probes"])


@router.get("/api/probes")
def list_probes(authorization: AuthHeader = None, chamber_id: int | None = None):
    require_user(authorization)
    with connect() as conn:
        if chamber_id:
            rows = conn.execute(
                """SELECT p.*, c.chamber_code, c.region FROM probes p
                   JOIN cold_chambers c ON c.id=p.chamber_id
                   WHERE p.chamber_id=? ORDER BY p.id""",
                (chamber_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT p.*, c.chamber_code, c.region FROM probes p
                   JOIN cold_chambers c ON c.id=p.chamber_id ORDER BY p.id"""
            ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/probes/{probe_id}")
def get_probe(probe_id: int, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        row = conn.execute(
            """SELECT p.*, c.name chamber_name, c.target_min, c.target_max
               FROM probes p JOIN cold_chambers c ON c.id=p.chamber_id
               WHERE p.id=?""",
            (probe_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "探头不存在")
        cals = conn.execute(
            "SELECT * FROM calibration_records WHERE probe_id=? ORDER BY id DESC",
            (probe_id,),
        ).fetchall()
        return {"probe": dict(row), "calibrations": [dict(x) for x in cals]}


@router.post("/api/probes")
def register_probe(body: ProbeIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        ch = conn.execute(
            "SELECT id FROM cold_chambers WHERE id=?", (body.chamber_id,)
        ).fetchone()
        if not ch:
            raise HTTPException(404, "仓间不存在")
        if conn.execute(
            "SELECT id FROM probes WHERE probe_code=?", (body.probe_code,)
        ).fetchone():
            raise HTTPException(409, "探头编码已存在")
        cur = conn.execute(
            """INSERT INTO probes(probe_code,chamber_id,model,online_status,
               calibration_due,created_at) VALUES (?,?,?,?,?,?)""",
            (
                body.probe_code,
                body.chamber_id,
                body.model,
                "在线",
                body.calibration_due,
                now_iso(),
            ),
        )
        write_audit(conn, user, "probe_register", body.probe_code, {"id": cur.lastrowid})
        conn.commit()
        return {"id": cur.lastrowid, "probe_code": body.probe_code, "online_status": "在线"}


@router.post("/api/probes/{probe_id}/offline")
def set_offline(probe_id: int, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        row = conn.execute("SELECT * FROM probes WHERE id=?", (probe_id,)).fetchone()
        if not row:
            raise HTTPException(404, "探头不存在")
        conn.execute(
            "UPDATE probes SET online_status='离线' WHERE id=?", (probe_id,)
        )
        write_audit(conn, user, "probe_offline", row["probe_code"], {})
        conn.commit()
        return {"id": probe_id, "online_status": "离线"}


@router.post("/api/probes/{probe_id}/writeback")
def writeback_points(
    probe_id: int, body: ProbeWritebackIn, authorization: AuthHeader = None
):
    """探头回写挂接批次温度采样点。

    甲路径：封批代已生效则正式表零改并拒写，偏离已封纪要记温度点偏航；
    同批改点须抢批次锁，后到会话只记争用痕不写采样点。
    """
    user = require_writer(authorization)
    lock_key = f"batch:{body.batch_id}"
    with connect() as conn:
        require_lock(conn, lock_key, user)
        try:
            batch = conn.execute(
                "SELECT * FROM temp_batches WHERE id=?", (body.batch_id,)
            ).fetchone()
            if not batch:
                raise HTTPException(404, "批次不存在")
            if batch["probe_id"] != probe_id:
                raise HTTPException(422, "探头与批次挂接不符")
            probe = conn.execute(
                "SELECT * FROM probes WHERE id=?", (probe_id,)
            ).fetchone()
            if not probe:
                raise HTTPException(404, "探头不存在")
            validate_probe_online(probe)
            if batch["status"] == "已封批":
                memo = conn.execute(
                    """SELECT m.id FROM seal_point_memos m
                       JOIN seal_snapshots s ON s.id=m.seal_id
                       WHERE m.batch_id=?
                       ORDER BY s.batch_generation DESC, m.id DESC LIMIT 1""",
                    (body.batch_id,),
                ).fetchone()
                memo_tag = f"纪要#{memo['id']}" if memo else "纪要缺失"
                record_point_deviation(
                    conn,
                    body.batch_id,
                    user,
                    body.points,
                    f"偏离已封{memo_tag}（甲路径零改）：封批后回写拒写",
                    "回写拒写",
                )
                write_audit(
                    conn,
                    user,
                    "temp_point_deviation",
                    batch["batch_code"],
                    {"rejected_points": len(body.points)},
                )
                conn.commit()
                raise HTTPException(
                    409,
                    "已封批：温度点正式表零改（甲路径），回写拒写并记温度点偏航",
                )
            ch = conn.execute(
                "SELECT target_min, target_max FROM cold_chambers WHERE id=?",
                (batch["chamber_id"],),
            ).fetchone()
            for pt in body.points:
                validate_temp_point(
                    float(pt.get("c", pt.get("temp", 0))),
                    float(ch["target_min"]),
                    float(ch["target_max"]),
                )
            points = json.loads(batch["temp_points"] or "[]") + body.points
            tmin, tmax = summarize_points(points)
            status = "已入库" if batch["status"] == "草稿" else batch["status"]
            conn.execute(
                """UPDATE temp_batches SET temp_points=?, min_observed=?,
                   max_observed=?, status=? WHERE id=?""",
                (
                    json.dumps(points, ensure_ascii=False),
                    tmin,
                    tmax,
                    status,
                    body.batch_id,
                ),
            )
            write_audit(
                conn,
                user,
                "probe_writeback",
                batch["batch_code"],
                {"batch_id": body.batch_id, "appended": len(body.points)},
            )
            conn.commit()
            return {
                "batch_id": body.batch_id,
                "batch_code": batch["batch_code"],
                "point_count": len(points),
                "status": status,
            }
        finally:
            release(conn, lock_key, user)
            conn.commit()