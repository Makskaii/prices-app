# app/api/docs.py
import os
from flask import Blueprint, request, send_file, current_app
from io import BytesIO
from datetime import date

from app.services.bitrix_api import fetch_deal_with_extras
from app.docgen import build_pdf_from_template, format_money
from app.database import db
from app.models.proposal_counter import ProposalCounter
from app.docgen_docx import build_docx_for_variant

from app.services.bitrix_disk_service import (
    upload_docx_to_disk_replace,
    get_disk_file_detail_url,
    set_deal_kp_link,
    upload_docx_to_deal_file_field,
    set_quote_kp_link,
    upload_docx_to_quote_file_field,
    _sanitize_filename,
    KP_FOLDER_ID,
)


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

    days_in_month = [
        31,
        29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31
    ][month - 1]
    day = min(d.day, days_in_month)
    return date(year, month, day)


def get_next_offer_number_for_company(company_id: str | None) -> int | None:
    """
    Счётчик КП по компании (если захочешь использовать).
    Сейчас не используется в имени файла, оставлено как у тебя.
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


def _safe_name_part(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    safe = "".join(ch if ch.isalnum() or ch in (" ", "_", "-", ".") else "_" for ch in s)
    safe = " ".join(safe.split()).strip()
    return safe[:max_len]


@bp.post("/generate")
def generate():
    data = request.get_json() or {}

    variant = data.get("variant") or "kp_tp_discount"
    out_format = (data.get("format") or "pdf").lower()

    # ✅ новый универсальный формат:
    # mode: "DEAL"|"QUOTE", entity_id: "123"
    # (для совместимости оставляем deal_id)
    mode = (data.get("mode") or "DEAL").upper().strip()
    entity_id = data.get("entity_id") or data.get("deal_id") or 0

    try:
        entity_id_int = int(entity_id)
    except Exception:
        entity_id_int = 0

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

    # --------- extras (только для сделок) ----------
    if entity_id_int and mode == "DEAL":
        try:
            extra = fetch_deal_with_extras(entity_id_int)

            context["deal_company"] = extra.get("deal_company") or None
            context["contact_name"] = extra.get("contact_name") or None
            context["contact_email"] = extra.get("contact_email") or None
            context["manager_name"] = extra.get("manager_name") or None
            context["manager_email"] = extra.get("manager_email") or None
            context["manager_phone"] = extra.get("manager_phone") or None

            context["offer_date"] = today.strftime("%d.%m.%Y")

            deal_title = (extra.get("deal_title") or "").strip()
            context["offer_number"] = deal_title if deal_title else str(entity_id_int)

        except Exception:
            current_app.logger.exception("Bitrix error for deal %s", entity_id_int)

    # --------- если QUOTE: хотя бы базовые значения ----------
    if entity_id_int and mode == "QUOTE":
        context["offer_date"] = today.strftime("%d.%m.%Y")
        # номер берём из id (если нужно иначе — можно подтянуть crm.item.get отдельно)
        context["offer_number"] = str(entity_id_int)

    # страховки
    if not context.get("offer_date"):
        context["offer_date"] = today.strftime("%d.%m.%Y")

    if not context.get("valid_until"):
        context["valid_until"] = add_months(today, 3).strftime("%d.%m.%Y")

    for key in [
        "deal_company",
        "offer_number",
        "contact_name",
        "contact_email",
        "offer_date",
        "manager_name",
        "manager_email",
        "manager_phone",
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

    # ================= DOCX =================
    if out_format == "docx":
        docx_bytes = build_docx_for_variant(variant, context)

        # приятное имя файла
        offer_no = _safe_name_part(context.get("offer_number") or "", 40)
        deal_company = _safe_name_part(context.get("deal_company") or "", 60)

        if mode == "DEAL":
            if deal_company and offer_no:
                filename = f"КП_{deal_company}_№{offer_no}_сделка_{entity_id_int}.docx"
            elif deal_company:
                filename = f"КП_{deal_company}_сделка_{entity_id_int}.docx"
            else:
                filename = f"КП_сделка_{entity_id_int}.docx"
        else:
            # QUOTE
            if deal_company and offer_no:
                filename = f"КП_{deal_company}_№{offer_no}_предложение_{entity_id_int}.docx"
            elif deal_company:
                filename = f"КП_{deal_company}_предложение_{entity_id_int}.docx"
            else:
                filename = f"КП_предложение_{entity_id_int}.docx"

        filename = _sanitize_filename(filename)

        # --- загрузка в диск с replace по имени ---
        if entity_id_int and mode in ("DEAL", "QUOTE"):
            try:
                file_id = upload_docx_to_disk_replace(KP_FOLDER_ID, filename, docx_bytes)
                file_url = get_disk_file_detail_url(file_id)

                current_app.logger.info("KP saved to Disk (replace-by-name): file_id=%s url=%s", file_id, file_url)

                if mode == "DEAL":
                    # ссылка в сделку
                    try:
                        set_deal_kp_link(entity_id_int, file_url)
                    except Exception:
                        current_app.logger.exception("Failed to write KP link into DEAL (id=%s)", entity_id_int)

                    # файл в поле сделки (как было)
                    try:
                        upload_docx_to_deal_file_field(
                            deal_id=entity_id_int,
                            field_code="UF_CRM_1768830570994",
                            filename=filename,
                            content=docx_bytes
                        )
                        current_app.logger.info("KP uploaded to DEAL file field UF_CRM_1768830570994 (deal_id=%s)", entity_id_int)
                    except Exception:
                        current_app.logger.exception("Failed to upload KP into DEAL file field UF_CRM_1768830570994 (deal_id=%s)", entity_id_int)

                else:
                    # QUOTE: ссылка + файл в поля предложения
                    try:
                        set_quote_kp_link(entity_id_int, file_url)
                    except Exception:
                        current_app.logger.exception("Failed to write KP link into QUOTE (id=%s)", entity_id_int)

                    try:
                        upload_docx_to_quote_file_field(
                            quote_id=entity_id_int,
                            filename=filename,
                            content=docx_bytes
                        )
                        current_app.logger.info("KP uploaded to QUOTE file field ufCrm_697C815A39C78 (quote_id=%s)", entity_id_int)
                    except Exception:
                        current_app.logger.exception("Failed to upload KP into QUOTE file field ufCrm_697C815A39C78 (quote_id=%s)", entity_id_int)

            except Exception:
                current_app.logger.exception("KP upload to Disk failed (mode=%s id=%s)", mode, entity_id_int)

        return send_file(
            BytesIO(docx_bytes),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True,
            download_name="komercheskoe_predlozhenie.docx",
        )

    # ================= PDF =================
    pdf_bytes = build_pdf_from_template(template_name, context)
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="komercheskoe_predlozhenie.pdf",
    )
