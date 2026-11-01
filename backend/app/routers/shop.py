"""Oasis Shops: the owner's products (create, edit, photos, stock) and the public product photos."""

import json
import re
import secrets

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import db
from ..auth import User, current_user, optional_user
from ..checks import worker
from ..gateway import search_index
from ..shop import catalog, templates
from .workspaces import _owned

router = APIRouter(tags=["shop"])

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 8
MAX_SIDE = 1600   # the photo customers see
THUMB_SIDE = 480  # small copy for card views (sent inline when the photo's address can't load)
_FILE_NAME = re.compile(r"^[a-zA-Z0-9_-]{8,40}\.(jpg|png)$")


def _store_photo(data: bytes, folder, stem: str) -> str:
    """Check it really is a photo, keep it at most MAX_SIDE, and save a thumbnail. Returns the file name."""
    from io import BytesIO

    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(BytesIO(data)) as probe:
            probe.verify()
        img = Image.open(BytesIO(data))
        if img.format not in ("JPEG", "PNG", "WEBP"):
            raise HTTPException(400, "Only JPEG, PNG or WebP photos")
        img = ImageOps.exif_transpose(img)  # phone photos: upright
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise HTTPException(400, "Only JPEG, PNG or WebP photos") from exc
    alpha = img.mode in ("RGBA", "LA", "P") and "transparency" in img.info or img.mode in ("RGBA", "LA")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    name = f"{stem}.{'png' if alpha else 'jpg'}"
    if alpha:
        img.save(folder / name, "PNG", optimize=True)
    else:
        img.convert("RGB").save(folder / name, "JPEG", quality=85, optimize=True)
    thumb = img.convert("RGBA") if alpha else img.convert("RGB")
    thumb.thumbnail((THUMB_SIDE, THUMB_SIDE))
    if alpha:  # thumbnails are JPEG: put transparent parts on white
        bg = Image.new("RGB", thumb.size, "white")
        bg.paste(thumb, mask=thumb.split()[-1])
        thumb = bg
    thumb.save(folder / catalog.thumb_name(name), "JPEG", quality=78, optimize=True)
    return name


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=60)
    price_amount: float | None = Field(default=None, ge=0, le=1_000_000)
    currency: str = Field(default="CHF", min_length=3, max_length=3)
    attributes: dict = Field(default_factory=dict)
    options: dict = Field(default_factory=dict)
    stock: dict = Field(default_factory=dict)  # variant key -> count; {} = not tracked
    active: bool = True


class ProductPatch(ProductIn):
    name: str | None = Field(default=None, min_length=1, max_length=120)  # type: ignore[assignment]


class OrderIn(BaseModel):
    ids: list[str] = Field(max_length=500)


def _shop(conn, business_id: str, user: User):
    b = _owned(conn, business_id, user)
    if not b["shop_template"]:
        raise HTTPException(400, "This workspace is not an Oasis shop. Create a shop workspace to add products.")
    return b


def _product(conn, business_id: str, product_id: str):
    p = conn.execute("SELECT * FROM products WHERE id = ? AND business_id = ?", (product_id, business_id)).fetchone()
    if p is None:
        raise HTTPException(404, "Product not found")
    return p


def _clean(template: str, body: ProductIn) -> dict:
    options = templates.clean_options(template, body.options)
    stock: dict[str, int] = {}
    if templates.get(template)["stock"] and body.stock:
        keys = set(templates.variant_keys(options))
        for k, v in body.stock.items():
            if k in keys:
                try:
                    stock[k] = max(0, min(100_000, int(v)))
                except (TypeError, ValueError):
                    raise HTTPException(400, f"Stock for {k or 'the product'} must be a whole number") from None
    return {
        "name": body.name.strip() if body.name else body.name,
        "description": body.description.strip(),
        "category": body.category.strip(),
        "price_amount": round(body.price_amount, 2) if body.price_amount is not None else None,
        "currency": body.currency.upper(),
        "attributes": json.dumps(templates.clean_attributes(template, body.attributes), ensure_ascii=False),
        "options": json.dumps(options, ensure_ascii=False),
        "stock": json.dumps(stock),
        "active": int(body.active),
    }


def _shop_changed(business_id: str) -> None:
    """The shop's tool exists from the first product on; a new one is checked straight away."""
    made = catalog.ensure_tool(business_id)
    if made:
        worker.enqueue_for(made[0], made[1], "change")
    search_index.schedule(business_id)


@router.get("/api/shop/templates")
def shop_templates() -> dict:
    return templates.TEMPLATES


@router.get("/api/workspaces/{business_id}/products")
def list_products(business_id: str, user: User = Depends(current_user)) -> list[dict]:
    with db.session() as conn:
        _shop(conn, business_id, user)
        rows = conn.execute("SELECT * FROM products WHERE business_id = ? ORDER BY sort, created_at", (business_id,)).fetchall()
    return [catalog.product_out(r) for r in rows]


@router.post("/api/workspaces/{business_id}/products", status_code=201)
def create_product(business_id: str, body: ProductIn, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        b = _shop(conn, business_id, user)
        fields = _clean(b["shop_template"], body)
        pid, stamp = catalog.new_product_id(), db.now()
        sort = conn.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM products WHERE business_id = ?", (business_id,)).fetchone()[0]
        conn.execute(
            "INSERT INTO products (id, business_id, name, description, category, price_amount, currency, images, attributes, options, stock,"
            " active, sort, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?, ?)",
            (pid, business_id, fields["name"], fields["description"], fields["category"], fields["price_amount"], fields["currency"],
             fields["attributes"], fields["options"], fields["stock"], fields["active"], sort, stamp, stamp),
        )
        out = catalog.product_out(_product(conn, business_id, pid))
    _shop_changed(business_id)
    return out


@router.patch("/api/workspaces/{business_id}/products/{product_id}")
def update_product(business_id: str, product_id: str, body: ProductPatch, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        b = _shop(conn, business_id, user)
        current = catalog.product_out(_product(conn, business_id, product_id))
        merged = ProductIn(**{**{k: current[k] for k in ProductIn.model_fields}, **body.model_dump(exclude_unset=True)})
        fields = _clean(b["shop_template"], merged)
        conn.execute(
            "UPDATE products SET name = ?, description = ?, category = ?, price_amount = ?, currency = ?, attributes = ?, options = ?,"
            " stock = ?, active = ?, updated_at = ? WHERE id = ?",
            (fields["name"], fields["description"], fields["category"], fields["price_amount"], fields["currency"], fields["attributes"],
             fields["options"], fields["stock"], fields["active"], db.now(), product_id),
        )
        out = catalog.product_out(_product(conn, business_id, product_id))
    _shop_changed(business_id)
    return out


@router.delete("/api/workspaces/{business_id}/products/{product_id}", status_code=204)
def delete_product(business_id: str, product_id: str, user: User = Depends(current_user)) -> None:
    with db.session() as conn:
        _shop(conn, business_id, user)
        _product(conn, business_id, product_id)
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    search_index.schedule(business_id)
    import shutil

    shutil.rmtree(catalog.image_dir(business_id, product_id), ignore_errors=True)


@router.post("/api/workspaces/{business_id}/products/order")
def reorder_products(business_id: str, body: OrderIn, user: User = Depends(current_user)) -> list[dict]:
    with db.session() as conn:
        _shop(conn, business_id, user)
        for n, pid in enumerate(body.ids):
            conn.execute("UPDATE products SET sort = ? WHERE id = ? AND business_id = ?", (n, pid, business_id))
    return list_products(business_id, user)


@router.post("/api/workspaces/{business_id}/products/{product_id}/images", status_code=201)
async def upload_image(business_id: str, product_id: str, file: UploadFile = File(...), user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _shop(conn, business_id, user)
        p = _product(conn, business_id, product_id)
    images = json.loads(p["images"] or "[]")
    if len(images) >= MAX_IMAGES:
        raise HTTPException(400, f"At most {MAX_IMAGES} photos per product")
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "A photo can be at most 8 MB")
    folder = catalog.image_dir(business_id, product_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = _store_photo(data, folder, secrets.token_urlsafe(12).replace("-", "x"))
    with db.session() as conn:
        conn.execute("UPDATE products SET images = ?, updated_at = ? WHERE id = ?", (json.dumps(images + [name]), db.now(), product_id))
        return catalog.product_out(_product(conn, business_id, product_id))


@router.delete("/api/workspaces/{business_id}/products/{product_id}/images/{name}")
def delete_image(business_id: str, product_id: str, name: str, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _shop(conn, business_id, user)
        p = _product(conn, business_id, product_id)
        images = [n for n in json.loads(p["images"] or "[]") if n != name]
        conn.execute("UPDATE products SET images = ?, updated_at = ? WHERE id = ?", (json.dumps(images), db.now(), product_id))
        out = catalog.product_out(_product(conn, business_id, product_id))
    if _FILE_NAME.match(name):
        (catalog.image_dir(business_id, product_id) / name).unlink(missing_ok=True)
        (catalog.image_dir(business_id, product_id) / catalog.thumb_name(name)).unlink(missing_ok=True)
    return out


@router.post("/api/workspaces/{business_id}/products/{product_id}/images/order")
def reorder_images(business_id: str, product_id: str, body: OrderIn, user: User = Depends(current_user)) -> dict:
    with db.session() as conn:
        _shop(conn, business_id, user)
        p = _product(conn, business_id, product_id)
        current = json.loads(p["images"] or "[]")
        ordered = [n for n in body.ids if n in current] + [n for n in current if n not in body.ids]
        conn.execute("UPDATE products SET images = ?, updated_at = ? WHERE id = ?", (json.dumps(ordered), db.now(), product_id))
        return catalog.product_out(_product(conn, business_id, product_id))


@router.get("/api/public/shops/{business_id}/images/{product_id}/{name}", include_in_schema=False)
def public_image(business_id: str, product_id: str, name: str, user: User | None = Depends(optional_user)) -> FileResponse:
    """A product photo: public while the shop is live (assistants show it), otherwise only its owner."""
    if not _FILE_NAME.match(name):
        raise HTTPException(404, "Not found")
    with db.session() as conn:
        b = conn.execute("SELECT owner_id, status FROM businesses WHERE id = ?", (business_id,)).fetchone()
        p = conn.execute("SELECT images, active FROM products WHERE id = ? AND business_id = ?", (product_id, business_id)).fetchone()
    names = json.loads(p["images"] or "[]") if p else []
    if b is None or p is None or (name not in names and name not in {catalog.thumb_name(n) for n in names}):
        raise HTTPException(404, "Not found")
    if not (b["status"] == "live" and p["active"]) and not (user and (user.id == b["owner_id"] or user.is_admin)):
        raise HTTPException(404, "Not found")
    path = catalog.image_dir(business_id, product_id) / name
    if not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(path, headers={"cache-control": "public, max-age=3600"})
