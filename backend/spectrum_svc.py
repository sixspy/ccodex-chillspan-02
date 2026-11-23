"""温谱导出：曲线只认封批快照点列，与正式表零漂移。"""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from models import SpectrumIn

router = APIRouter(tags=["spectrum"])


def _latest_sealed_points(conn, batch_id: int) -> list | None:
    snap = conn.execute(
        """SELECT manifest FROM seal_snapshots WHERE batch_id=?
           ORDER BY batch_generation DESC, id DESC LIMIT 1""",
        (batch_id,),
    ).fetchone()
    if not snap:
        return None
    try:
        manifest = json.loads(snap["manifest"])
    except (TypeError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    return manifest.get("points")


@router.get("/api/spectrum")
def list_exports(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT s.*, b.batch_code FROM spectrum_exports s
               JOIN temp_batches b ON b.id=s.batch_id ORDER BY s.id DESC"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/spectrum/export")
def export_spectrum(body: SpectrumIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        batch = conn.execute(
            "SELECT * FROM temp_batches WHERE id=?", (body.batch_id,)
        ).fetchone()
        if not batch:
            raise HTTPException(404, "批次不存在")
        if batch["status"] != "已封批":
            raise HTTPException(409, "须先封批再导出温谱")
        points = _latest_sealed_points(conn, body.batch_id)
        if points is None:
            raise HTTPException(409, "封批快照缺失，禁止导出温谱")
        payload = json.dumps(
            {
                "batch_code": batch["batch_code"],
                "generation": batch["generation"],
                "points": points,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        ref = f"SP-{batch['batch_code']}-G{batch['generation']}"
        dup = conn.execute(
            "SELECT id FROM spectrum_exports WHERE export_ref=?", (ref,)
        ).fetchone()
        if dup:
            raise HTTPException(409, "该代温谱已导出")
        cur = conn.execute(
            """INSERT INTO spectrum_exports(batch_id,export_ref,point_count,checksum,
               status,created_at) VALUES (?,?,?,?,?,?)""",
            (
                body.batch_id,
                ref,
                len(points),
                checksum,
                "已导出",
                now_iso(),
            ),
        )
        write_audit(conn, user, "spectrum_export", ref, {"checksum": checksum})
        conn.commit()
        return {
            "id": cur.lastrowid,
            "export_ref": ref,
            "point_count": len(points),
            "checksum": checksum,
            "status": "已导出",
        }


@router.get("/api/spectrum/{export_ref}")
def get_export(export_ref: str, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        row = conn.execute(
            """SELECT s.*, b.batch_code FROM spectrum_exports s
               JOIN temp_batches b ON b.id=s.batch_id WHERE s.export_ref=?""",
            (export_ref,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "导出不存在")
        data = dict(row)
        points = _latest_sealed_points(conn, row["batch_id"])
        data["temp_points"] = points if points is not None else []
        return data