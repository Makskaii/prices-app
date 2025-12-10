from flask import Blueprint, request, jsonify, send_file, current_app
from io import BytesIO
from ..docgen import build_pdf_from_template

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


@bp.post("/generate")
def generate():
    data = request.get_json(silent=True) or {}

    doc_type = data.get("docType") or data.get("doc_type") or "kp_tp_discount"
    lines = data.get("lines") or []

    # инфа по клиенту / сделке – как ты уже отправляешь с фронта
    client = data.get("client") or {}
    deal = data.get("deal") or {}

    # пробуем взять totals из фронта, если он их присылает
    totals_raw = data.get("totals") or data.get("summary") or {}

    totals = _calc_totals(lines, totals_raw)

    context = {
        "lines": lines,
        "client": client,
        "deal": deal,
        "totals": totals,
    }

    if doc_type == "kp_tp_discount":
        template_name = "docs/kp_tp_discount.html"
        filename = f"KP_TP_so_skidkoy_{deal.get('number') or deal.get('id') or 'document'}.pdf"
    elif doc_type == "kp_tp":
        template_name = "docs/kp_tp.html"
        filename = f"KP_TP_{deal.get('number') or deal.get('id') or 'document'}.pdf"
    elif doc_type == "kp_supply":
        template_name = "docs/kp_supply.html"
        filename = f"KP_postavka_{deal.get('number') or deal.get('id') or 'document'}.pdf"
    else:
        return jsonify({"error": "Unknown docType"}), 400

    try:
        pdf_bytes = build_pdf_from_template(template_name, context)
    except Exception as e:
        current_app.logger.exception("Error while building PDF")
        return jsonify({"error": "pdf_render_error", "details": str(e)}), 500

    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )
