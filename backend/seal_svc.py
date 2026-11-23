"""封批升代 + 快照清单 + 封批温度点纪要（甲路径裁决落锤）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import (
    connect,
    ensure_seal_memo,
    now_iso,
    points_sha256,
    write_audit,
)
from locks import release, require_lock
from models import SealIn
from validators import require_calibration_fresh, validate_batch_sealable

router = APIRouter(tags=["seal"])


def _parse_manifest(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {"note": raw}
    return data if isinstance(data, dict) else {"note": raw}


@router.get("/api/seals")
def list_seals(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT s.*, b.batch_code, m.policy_path, m.locked AS memo_locked
               FROM seal_snapshots s
               JOIN temp_batches b ON b.id=s.batch_id
               LEFT JOIN seal_point_memos m ON m.seal_id=s.id
               ORDER BY s.id DESC"""
        ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            manifest = _parse_manifest(d["manifest"])
            d["note"] = manifest.get("note", "")
            d["point_count"] = manifest.get("point_count")
            d["points_sha"] = manifest.get("points_sha", "")
            items.append(d)
        return {"items": items}


@router.get("/api/seal-memos")
def list_seal_memos(authorization: AuthHeader = None):
    """封批温度点纪要：裁决口径当班封死，只读。"""
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT m.*, b.batch_code, s.batch_generation
               FROM seal_point_memos m
               JOIN temp_batches b ON b.id=m.batch_id
               JOIN seal_snapshots s ON s.id=m.seal_id
               ORDER BY m.id DESC"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/seal-deviations")
def list_seal_deviations(authorization: AuthHeader = None):
    """温度点偏航记录：偏离已封纪要的点列在此隔离，不进任何正式面。"""
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT d.*, b.batch_code FROM temp_point_deviations d
               JOIN temp_batches b ON b.id=d.batch_id
               ORDER BY d.id DESC LIMIT 200"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/seals")
def seal_batch(body: SealIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    lock_key = f"batch:{body.batch_id}"
    with connect() as conn:
        require_lock(conn, lock_key, user)
        try:
            batch = conn.execute(
                """SELECT b.*, p.calibration_due, p.probe_code
                   FROM temp_batches b JOIN probes p ON p.id=b.probe_id
                   WHERE b.id=?""",
                (body.batch_id,),
            ).fetchone()
            if not batch:
                raise HTTPException(404, "批次不存在")
            open_exc = conn.execute(
                """SELECT COUNT(*) c FROM excursion_cursors
                   WHERE batch_id=? AND status='开放'""",
                (body.batch_id,),
            ).fetchone()["c"]
            bdict = dict(batch)
            bdict["temp_points"] = batch["temp_points"]
            validate_batch_sealable(bdict, open_exc)
            require_calibration_fresh(batch)
            gen = int(batch["generation"])
            points = json.loads(batch["temp_points"] or "[]")
            manifest_obj = {
                "batch_code": batch["batch_code"],
                "generation": gen + 1,
                "point_count": len(points),
                "min": batch["min_observed"],
                "max": batch["max_observed"],
                "points": points,
                "points_sha": points_sha256(points),
            }
            if body.manifest:
                manifest_obj["note"] = body.manifest
            manifest = json.dumps(manifest_obj, ensure_ascii=False)
            now = now_iso()
            cur = conn.execute(
                """INSERT INTO seal_snapshots(batch_id,batch_generation,manifest,status,sealed_at)
                   VALUES (?,?,?,?,?)""",
                (body.batch_id, gen + 1, manifest, "已封批", now),
            )
            conn.execute(
                """UPDATE temp_batches SET status='已封批', generation=generation+1,
                   sealed_at=? WHERE id=?""",
                (now, body.batch_id),
            )
            ensure_seal_memo(
                conn, body.batch_id, cur.lastrowid, manifest_obj, user, now
            )
            write_audit(
                conn,
                user,
                "batch_seal",
                batch["batch_code"],
                {"seal_id": cur.lastrowid, "generation": gen + 1},
            )
            conn.commit()
            return {
                "seal_id": cur.lastrowid,
                "batch_code": batch["batch_code"],
                "generation": gen + 1,
                "status": "已封批",
            }
        finally:
            release(conn, lock_key, user)