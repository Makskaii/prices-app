import os
from flask import Blueprint, request, jsonify, send_file, current_app
from io import BytesIO
from datetime import datetime, date, timedelta
from app.services.bitrix_api import fetch_deal_with_extras
from app.docgen import build_pdf_from_template, format_money
from app.database import db
from app.models.proposal_counter import ProposalCounter
from app.docgen_docx import build_docx_for_variant
from app.services.bitrix_disk_service import save_kp_and_write_link, upload_docx_to_deal_file_field




bp = Blueprint("docs", __name__, url_prefix="/api/docs")


def _safe_num(value):
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _format_money(num: float) -> str:
    """
    Форматирование как в фронте: 12 345,67
    """
    num = float(num or 0)
    s = f"{num:,.2f}"
    s = s.replace(",", " ")
    s = s.replace(".", ",")
    return s


def _calc_totals(lines, totals_from_client=None):
    """
    Считает суммы по строкам, если клиент ничего не прислал.
    Если прислал — берём их, но всё равно нормализуем и добавляем *_fmt.
    """
    base = discount = vat = total = 0.0

    if totals_from_client:
        base = _safe_num(totals_from_client.get("base"))
        discount = _safe_num(totals_from_client.get("discount"))
        vat = _safe_num(totals_from_client.get("vat"))
        total = _safe_num(totals_from_client.get("total"))
    else:
        for line in (lines or []):
            price = _safe_num(line.get("price"))
            qty = _safe_num(line.get("quantity") or 1)
            base_line = _safe_num(line.get("base", price * qty))
            discount_line = _safe_num(line.get("discountAmount"))
            vat_line = _safe_num(line.get("vatAmount"))
            total_line = _safe_num(line.get("total", base_line - discount_line + vat_line))

            base += base_line
            discount += discount_line
            vat += vat_line
            total += total_line

    return {
        "base": base,
        "discount": discount,
        "vat": vat,
        "total": total,
        "base_fmt": _format_money(base),
        "discount_fmt": _format_money(discount),
        "vat_fmt": _format_money(vat),
        "total_fmt": _format_money(total),
    }

def add_months(d: date, months: int) -> date:
    """
    Аккуратно добавляем N месяцев к дате, чтобы не улететь за пределы месяца.
    """
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1

    # количество дней в месяце
    days_in_month = [31,
                     29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    day = min(d.day, days_in_month)
    return date(year, month, day)

def get_next_offer_number_for_company(company_id: str | None) -> int | None:
    """
    Возвращает следующий номер предложения для данной компании.
    company_id — это ID компании из Bitrix (строкой).
    Если company_id нет, вернём None и дальше можно fallback-нуть к deal_id.
    """
    if not company_id:
        return None

    pc = ProposalCounter.query.filter_by(company_id=company_id).first()
    if pc is None:
        pc = ProposalCounter(company_id=company_id, counter=1)
        db.session.add(pc)
    else:
        pc.counter += 1

    db.session.commit()
    return pc.counter

@bp.post("/generate")
def generate():
    data = request.get_json() or {}
    variant = data.get("variant") or "kp_tp_discount"
    out_format = (data.get("format") or "pdf").lower()
    deal_id = data.get("deal_id")
    lines = data.get("lines") or []

    totals_from_client = data.get("totals")
    totals = _calc_totals(lines, totals_from_client)

    context: dict = {
        "lines": lines,
        "totals": totals,
        "format_money": format_money,

        "deal_company": None,
        "offer_number": None,
        "contact_name": None,
        "contact_email": None,
        "offer_date": None,
        "valid_until": None,
        "manager_name": None,
        "manager_email": None,
        "manager_phone": None,
    }

    today = date.today()

    if deal_id:
        try:
            deal_id_int = int(deal_id)
            extra = fetch_deal_with_extras(deal_id_int)

            context["deal_company"] = extra.get("deal_company") or None
            context["contact_name"] = extra.get("contact_name") or None
            context["contact_email"] = extra.get("contact_email") or None
            context["manager_name"] = extra.get("manager_name") or None
            context["manager_email"] = extra.get("manager_email") or None
            context["manager_phone"] = extra.get("manager_phone") or None

            # Дата КП = дата формирования документа
            context["offer_date"] = today.strftime("%d.%m.%Y")

            deal_title = (extra.get("deal_title") or "").strip()
            context["offer_number"] = deal_title if deal_title else str(deal_id_int)


        except Exception:
            current_app.logger.exception("Bitrix error for deal %s", deal_id)

    # страховки
    if not context.get("offer_date"):
        context["offer_date"] = today.strftime("%d.%m.%Y")

    if not context.get("valid_until"):
        context["valid_until"] = add_months(today, 3).strftime("%d.%m.%Y")

    for key, default in [
        ("deal_company", "Контрагент"),
        ("offer_number", "—"),
        ("contact_name", "ФИО контакта"),
        ("contact_email", "email контакта"),
        ("offer_date", "Дата составления КП"),
        ("manager_name", "Ответственный за сделку"),
        ("manager_email", "email ответственного за сделку"),
        ("manager_phone", "телефон ответственного за сделку"),
    ]:
        context.setdefault(key, None)

    # выбор шаблона
    if variant == "kp_tp_discount":
        template_name = "docs/kp_tp_discount.html"
    elif variant == "kp_tp_basic":
        template_name = "docs/kp_tp_basic.html"
    elif variant == "kp_tp_no_vat":
        template_name = "docs/kp_tp_no_vat.html"
    elif variant == "kp_tp_no_vat_nodiscount":
        template_name = "docs/kp_tp_no_vat_nodiscount.html"
    elif variant == "kp_delivery":
        template_name = "docs/kp_supply.html"
    else:
        template_name = "docs/kp_tp_discount.html"

    if out_format == "docx":
        docx_bytes = build_docx_for_variant(variant, context)

        # deal_id приходит из фронта в data
        try:
            deal_id_int = int(data.get("deal_id") or 0)
        except Exception:
            deal_id_int = 0

        if deal_id_int:
            # сделаем имя файла чуть приятнее
            offer_no = (context.get("offer_number") or "").strip()
            deal_company = (context.get("deal_company") or "").strip()

            # безопасное имя (без / \ : и т.п.)
            safe_company = "".join(ch if ch.isalnum() or ch in (" ", "_", "-", ".") else "_" for ch in deal_company)[:60].strip()
            safe_offer = "".join(ch if ch.isalnum() or ch in (" ", "_", "-", ".") else "_" for ch in offer_no)[:40].strip()

            if safe_company and safe_offer:
                filename = f"КП_{safe_company}_№{safe_offer}_сделка_{deal_id_int}.docx"
            elif safe_company:
                filename = f"КП_{safe_company}_сделка_{deal_id_int}.docx"
            else:
                filename = f"КП_сделка_{deal_id_int}.docx"

            try:
                info = save_kp_and_write_link(deal_id=deal_id_int, filename=filename, content=docx_bytes)
                current_app.logger.info("KP saved to Disk: %s", info)
            except Exception:
                current_app.logger.exception("save_kp_and_write_link failed (deal_id=%s)", deal_id_int)


            # 3) ВТОРОЙ ВАРИАНТ: загрузить этот же docx в поле типа "Файл" сделки
            try:
                upload_docx_to_deal_file_field(
                    deal_id=deal_id_int,
                    field_code="UF_CRM_1768830570994",
                    filename=filename,
                    content=docx_bytes
                )
                current_app.logger.info("KP uploaded to deal file field UF_CRM_1768830570994 (deal_id=%s)", deal_id_int)
            except Exception:
                current_app.logger.exception("Failed to upload KP into deal file field UF_CRM_1768830570994 (deal_id=%s)", deal_id_int)

        return send_file(
            BytesIO(docx_bytes),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True,
            download_name="komercheskoe_predlozhenie.docx",
        )



    pdf_bytes = build_pdf_from_template(template_name, context)

    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="komercheskoe_predlozhenie.pdf",
    )