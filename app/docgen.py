# app/docgen.py
from io import BytesIO
from datetime import date, datetime

from flask import current_app, render_template, url_for
from weasyprint import HTML
import os

def format_money(value) -> str:
    """
    Форматирование как в виджете: 12 345,67.
    Принимает любое числовое значение или строку.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        num = 0.0

    s = f"{num:.2f}"
    int_part, dec_part = s.split(".")

    # убираем возможные пробелы/неразрывные
    int_part = int_part.replace("\xa0", "").replace(" ", "")

    # разбиваем по 3 разряда с конца
    int_part = int_part[::-1]
    groups = [int_part[i:i + 3] for i in range(0, len(int_part), 3)]
    int_part = " ".join(groups)[::-1]

    return f"{int_part},{dec_part}"

def build_pdf_from_template(template_name: str, context: dict | None) -> bytes:
    """
    Рендерит HTML-шаблон и возвращает PDF как bytes.
    В контекст добавляем вспомогательные функции и путь к логотипу.
    """
    if context is None:
        context = {}

    ctx = dict(context)

    # функция форматирования доступна в шаблоне как {{ format_money(...) }}
    ctx.setdefault("format_money", format_money)

    # путь к логотипу как file://... чтобы WeasyPrint его увидел
    static_folder = current_app.static_folder or os.path.join(current_app.root_path, "static")
    logo_path = os.path.join(static_folder, "geotek_logo.png")
    if os.path.exists(logo_path):
        ctx.setdefault("logo_url", "file://" + logo_path)

    html = render_template(template_name, **ctx)
    pdf = HTML(string=html, base_url=current_app.root_path).write_pdf()
    return pdf


def build_doc_context(payload: dict) -> dict:
    """
    Преобразует данные из фронта (линии, суммы, реквизиты) в контекст для шаблона.
    Ожидаемый payload (пример):
    {
        "template": "tp_discount",  # или "tp", "supply"
        "offer_number": "123/25",
        "offer_date": "2025-02-01",
        "client_name": "...",
        "client_city": "...",
        "client_phone": "...",
        "manager_name": "...",
        "lines": [
           {
             "productName": "...",
             "quantity": 2,
             "price": 1000,
             "discountPercent": 5,
             "vatPercent": 20,
             "total": 2280
           },
           ...
        ]
    }
    """
    lines = payload.get("lines", []) or []

    items = []
    total_no_vat = 0.0
    total_vat = 0.0
    total = 0.0

    for l in lines:
        name = l.get("productName") or ""
        qty = float(l.get("quantity") or 0)
        price = float(l.get("price") or 0)
        discount_percent = float(l.get("discountPercent") or 0)
        vat_percent = float(l.get("vatPercent") or 0)
        line_total = float(l.get("total") or price * qty)

        base = price * qty
        discount_amount = base * (discount_percent / 100.0)
        base_after_discount = base - discount_amount
        vat_amount = base_after_discount * (vat_percent / 100.0)

        total_no_vat += base_after_discount
        total_vat += vat_amount
        total += base_after_discount + vat_amount

        items.append({
            "name": name,
            "quantity": qty,
            "price": price,
            "price_formatted": format_money(price),
            "discount_percent": discount_percent,
            "vat_percent": vat_percent,
            "total": base_after_discount + vat_amount,
            "total_formatted": format_money(base_after_discount + vat_amount),
        })

    ctx = {
        "offer_number": payload.get("offer_number") or payload.get("deal_id") or "",
        "offer_date": payload.get("offer_date")
                       or datetime.now().strftime("%d.%m.%Y"),
        "client_name": payload.get("client_name") or "",
        "client_city": payload.get("client_city") or "",
        "client_phone": payload.get("client_phone") or "",
        "manager_name": payload.get("manager_name") or "",
        "items": items,
        "total_no_vat": total_no_vat,
        "total_no_vat_formatted": format_money(total_no_vat),
        "total_vat": total_vat,
        "total_vat_formatted": format_money(total_vat),
        "total": total,
        "total_formatted": format_money(total),
    }

    return ctx
