"""The owner's order inbox: orders customers sent through Oasis (gateway/orders.py)."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..auth import User, current_user
from ..gateway import orders
from .workspaces import _owned

router = APIRouter(prefix="/api/workspaces/{business_id}", tags=["orders"])


class DecideIn(BaseModel):
    status: Literal["accepted", "declined"]
    note: str = Field(default="", max_length=300)


def _out(o) -> dict:
    d = db.row(o, ("items",))
    d.pop("status_token", None)
    return d


@router.get("/orders")
def list_orders(business_id: str, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        b = _owned(conn, business_id, user)
        rows = conn.execute(
            "SELECT * FROM orders WHERE business_id = ? ORDER BY status = 'pending' DESC, created_at DESC LIMIT 100", (business_id,)
        ).fetchall()
        has_catalog = bool(orders.catalog_tools(conn, business_id))
    return {
        "accepts_orders": bool(b["accepts_orders"]),
        "has_catalog": has_catalog,
        "pending": sum(r["status"] == "pending" for r in rows),
        "orders": [_out(r) for r in rows],
    }


@router.post("/orders/{order_id}")
def decide(business_id: str, order_id: str, body: DecideIn, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _owned(conn, business_id, user)
        cur = conn.execute(
            "UPDATE orders SET status = ?, owner_note = ?, updated_at = ? WHERE id = ? AND business_id = ? AND status = 'pending'",
            (body.status, body.note.strip(), db.now(), order_id, business_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "This order was already answered, or it doesn't exist")
    return list_orders(business_id, user)
