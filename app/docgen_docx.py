# app/docgen_docx.py
from __future__ import annotations

import os
from io import BytesIO
from typing import Any, Dict, List, Tuple

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt


DOCX_TABLE_FONT_PT = 9


def _safe_num(v) -> float:
    try:
        if v is None or v == "":
            return 0.0
        return float(v)
    except Exception:
        return 0.0


def _fmt_money(num: float) -> str:
    num = float(num or 0.0)
    s = f"{num:,.2f}"
    s = s.replace(",", " ")
    s = s.replace(".", ",")
    return s


def _set_cell_text(cell, text: str, bold: bool = False, size_pt: int | None = None,
                   align: int | None = None) -> None:
    cell.text = ""
    p = cell.paragraphs[0]
    if align is not None:
        p.alignment = align

    # важно: разрешаем перенос слов внутри ячейки (чтобы текст не раздвигал таблицу)
    p.paragraph_format.word_wrap = True

    run = p.add_run(text or "")
    run.bold = bool(bold)
    if size_pt is not None:
        run.font.size = Pt(size_pt)


def _set_table_borders(table, top=True, bottom=True, left=False, right=False,
                       inside_h=False, inside_v=False, size: int = 6) -> None:
    tbl = table._tbl
    tblPr = tbl.tblPr
    tblBorders = tblPr.find(qn("w:tblBorders"))
    if tblBorders is None:
        tblBorders = OxmlElement("w:tblBorders")
        tblPr.append(tblBorders)

    def _edge(name: str, enabled: bool):
        el = tblBorders.find(qn(f"w:{name}"))
        if el is None:
            el = OxmlElement(f"w:{name}")
            tblBorders.append(el)
        if enabled:
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), str(size))
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), "000000")
        else:
            el.set(qn("w:val"), "nil")

    _edge("top", top)
    _edge("bottom", bottom)
    _edge("left", left)
    _edge("right", right)
    _edge("insideH", inside_h)
    _edge("insideV", inside_v)


def _add_spacer(doc: Document, mm: int) -> None:
    p = doc.add_paragraph("")
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Mm(mm)
    p.paragraph_format.line_spacing = 1


def _calc_line_numbers(line: Dict[str, Any]) -> Dict[str, float]:
    price = _safe_num(line.get("price"))
    qty = _safe_num(line.get("quantity") or 0)
    discount_p = _safe_num(line.get("discountPercent"))
    vat_p = _safe_num(line.get("vatPercent"))

    base = price * qty
    discount_val = base * (discount_p / 100.0)
    base_after_discount = base - discount_val
    vat_val = base_after_discount * (vat_p / 100.0)
    total_val = base_after_discount + vat_val

    return {
        "price": price,
        "qty": qty,
        "base": base,
        "discount_val": discount_val,
        "base_after_discount": base_after_discount,
        "vat_val": vat_val,
        "total_val": total_val,
    }


def _resolve_logo_path(context: Dict[str, Any]) -> str | None:
    for key in ("logo_path", "logo_file"):
        p = context.get(key)
        if p and os.path.exists(p):
            return p

    candidate = os.path.join(os.getcwd(), "app", "static", "geotek_logo.png")
    if os.path.exists(candidate):
        return candidate
    return None


def _apply_page_setup(doc: Document) -> None:
    section = doc.sections[0]
    # A4 по умолчанию обычно и так, но отступы — как в PDF
    section.top_margin = Mm(20)
    section.bottom_margin = Mm(20)
    section.left_margin = Mm(20)
    section.right_margin = Mm(15)


def _add_header_with_logo(doc: Document, context: Dict[str, Any]) -> None:
    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False
    table.columns[0].width = Mm(115)
    table.columns[1].width = Mm(60)

    left_cell = table.cell(0, 0)
    right_cell = table.cell(0, 1)

    p_left = left_cell.paragraphs[0]
    p_left.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p_left.add_run("Коммерческое предложение")
    r.bold = True
    r.font.size = Pt(14)

    p_right = right_cell.paragraphs[0]
    p_right.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    logo_path = _resolve_logo_path(context)
    if logo_path:
        try:
            p_right.add_run().add_picture(logo_path, width=Mm(35))
        except Exception:
            pass

    _add_spacer(doc, 2)


def _add_requisites_block(doc: Document) -> None:
    table = doc.add_table(rows=1, cols=2)
    table.autofit = False
    table.columns[0].width = Mm(85)
    table.columns[1].width = Mm(85)

    _set_table_borders(table, top=True, bottom=True, left=False, right=False, inside_h=False, inside_v=False, size=6)

    left = table.cell(0, 0)
    right = table.cell(0, 1)
    left.vertical_alignment = WD_ALIGN_VERTICAL.TOP
    right.vertical_alignment = WD_ALIGN_VERTICAL.TOP

    left_text = (
        "450015, Республика Башкортостан, г. Уфа, ул. К. Маркса, 37, корп. 4, к. 514\n"
        "Тел./факс (347) 291-12-06, 291-12-07\n"
        "E-mail: prime@geotec.ru\n"
        "Web: http://www.primegeo.ru"
    )
    right_text = (
        "Регистрирующий орган: ИФНС России по Ленинскому району г. Уфы\n"
        "ОГРН: 1080275002389, дата регистрации: 23 июля 2008 г.\n"
        "ИНН: 0275065098 / КПП 027501001\n"
        "р/с 40702810530620006390\n"
        "в филиале «Центральный» Банка ВТБ (ПАО) в г. Москве\n"
        "кор. счёт: 30101810145250000411, БИК 044525411"
    )

    _set_cell_text(left, left_text, bold=False, size_pt=9, align=WD_ALIGN_PARAGRAPH.LEFT)
    _set_cell_text(right, right_text, bold=False, size_pt=9, align=WD_ALIGN_PARAGRAPH.LEFT)
    _add_spacer(doc, 3)


def _add_info_block(doc: Document, context: Dict[str, Any]) -> None:
    table = doc.add_table(rows=3, cols=2)
    table.autofit = False
    table.columns[0].width = Mm(85)
    table.columns[1].width = Mm(85)
    _set_table_borders(table, top=False, bottom=False, left=False, right=False, inside_h=False, inside_v=False)

    deal_company = context.get("deal_company") or "Контрагент"
    offer_number = context.get("offer_number") or "—"
    contact_name = context.get("contact_name") or "ФИО контакта"
    contact_email = context.get("contact_email") or "email контакта"
    offer_date = context.get("offer_date") or "Дата составления КП"

    _set_cell_text(table.cell(0, 0), f"Предложение для: {deal_company}", size_pt=10)
    _set_cell_text(table.cell(0, 1), f"Номер предложения: {offer_number}", size_pt=10)

    _set_cell_text(table.cell(1, 0), f"Получатель: {contact_name}", size_pt=10)
    _set_cell_text(table.cell(1, 1), f"Дата составления КП: {offer_date}", size_pt=10)

    table.cell(2, 0).merge(table.cell(2, 1))
    _set_cell_text(table.cell(2, 0), f"e-mail: {contact_email}", size_pt=10)
    _add_spacer(doc, 2)


def _add_valid_until(doc: Document, context: Dict[str, Any]) -> None:
    valid_until = context.get("valid_until") or ""
    p = doc.add_paragraph(f"Настоящее предложение действует до {valid_until}")
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if p.runs:
        p.runs[0].bold = True
        p.runs[0].font.size = Pt(10)
    _add_spacer(doc, 4)


def _add_center_title(doc: Document, text: str, bold: bool = True, size_pt: int = 11, after_mm: int = 3) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text)
    r.bold = bool(bold)
    r.font.size = Pt(size_pt)
    _add_spacer(doc, after_mm)


def _variant_columns(variant: str) -> Tuple[List[str], List[int]]:
    """
    widths в миллиметрах. Важно: сумма должна быть <= (210 - 20 - 15) = 175мм
    """
    if variant == "kp_tp_basic":
        headers = ["№", "Программное обеспечение PrimeGeo", "Кол-во, ед.", "Цена, руб.", "Стоимость, руб.", "Сумма НДС, руб.", "Стоимость с НДС, руб."]
        widths =  [7,   70,                                14,          18,           20,              18,             20]
        return headers, widths

    if variant == "kp_tp_no_vat":
        headers = ["№", "Программное обеспечение PrimeGeo", "Кол-во, ед.", "Цена, руб.", "Стоимость, руб.", "Стоимость со скидкой, руб."]
        widths =  [7,   82,                                14,          20,           22,              28]
        return headers, widths

    if variant == "kp_tp_no_vat_nodiscount":
        headers = ["№", "Программное обеспечение PrimeGeo", "Кол-во, ед.", "Цена, руб.", "Стоимость, руб."]
        widths =  [7,   100,                               14,          22,           32]
        return headers, widths

    headers = ["№", "Программное обеспечение PrimeGeo", "Кол-во, ед.", "Цена, руб.", "Стоимость, руб.",
               "Стоимость со скидкой, руб.", "Сумма НДС, руб.", "Стоимость с НДС, руб."]
    widths =  [7,   62,                                14,          16,           18,                 24,               16,             18]
    return headers, widths


# ---------- ВАЖНО: фиксация layout таблицы (чтобы не "уезжала") ----------

def _mm_to_twips(mm: int) -> int:
    # 1 inch = 25.4 mm, 1 twip = 1/1440 inch
    return int(mm * 1440 / 25.4)


def _force_fixed_table_layout(table, total_width_mm: int) -> None:
    """
    Говорим Word: таблица фиксированная и заданной ширины.
    Это убирает расползание на разных Word/LibreOffice.
    """
    tbl = table._tbl
    tblPr = tbl.tblPr

    # w:tblLayout w:type="fixed"
    tblLayout = tblPr.find(qn("w:tblLayout"))
    if tblLayout is None:
        tblLayout = OxmlElement("w:tblLayout")
        tblPr.append(tblLayout)
    tblLayout.set(qn("w:type"), "fixed")

    # w:tblW w:type="dxa" w:w="..."
    tblW = tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = OxmlElement("w:tblW")
        tblPr.append(tblW)
    tblW.set(qn("w:type"), "dxa")
    tblW.set(qn("w:w"), str(_mm_to_twips(total_width_mm)))


def _apply_column_widths_strict(table, widths_mm: List[int]) -> None:
    """
    Назначаем ширину:
      - колонкам
      - каждой ячейке каждой строки
    Иначе Word иногда "забывает" widths при рендере.
    """
    for i, w in enumerate(widths_mm):
        table.columns[i].width = Mm(w)

    for row in table.rows:
        for i, w in enumerate(widths_mm):
            row.cells[i].width = Mm(w)


def _add_products_table(doc: Document, variant: str, lines: List[Dict[str, Any]], totals: Dict[str, float]) -> None:
    headers, widths = _variant_columns(variant)

    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT

    # фиксируем layout и ширину таблицы (в пределах печатной области)
    total_w = sum(widths)
    _force_fixed_table_layout(table, total_w)
    _apply_column_widths_strict(table, widths)

    # заголовок
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        _set_cell_text(cell, h, bold=True, size_pt=DOCX_TABLE_FONT_PT, align=WD_ALIGN_PARAGRAPH.CENTER)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    # строки
    for idx, line in enumerate(lines, start=1):
        nums = _calc_line_numbers(line)
        name = line.get("productName") or ""

        row_cells = table.add_row().cells
        # после add_row — ещё раз жёстко назначаем ширины ячеек
        for i, w in enumerate(widths):
            row_cells[i].width = Mm(w)

        def setc(ci: int, text: str, align=WD_ALIGN_PARAGRAPH.LEFT):
            _set_cell_text(row_cells[ci], text, bold=False, size_pt=DOCX_TABLE_FONT_PT, align=align)
            row_cells[ci].vertical_alignment = WD_ALIGN_VERTICAL.TOP

        setc(0, str(idx), WD_ALIGN_PARAGRAPH.CENTER)
        setc(1, name, WD_ALIGN_PARAGRAPH.LEFT)
        setc(2, str(int(nums["qty"])), WD_ALIGN_PARAGRAPH.CENTER)

        if variant == "kp_tp_no_vat_nodiscount":
            setc(3, _fmt_money(nums["price"]), WD_ALIGN_PARAGRAPH.RIGHT)
            setc(4, _fmt_money(nums["base"]), WD_ALIGN_PARAGRAPH.RIGHT)

        elif variant == "kp_tp_no_vat":
            setc(3, _fmt_money(nums["price"]), WD_ALIGN_PARAGRAPH.RIGHT)
            setc(4, _fmt_money(nums["base"]), WD_ALIGN_PARAGRAPH.RIGHT)
            setc(5, _fmt_money(nums["base_after_discount"]), WD_ALIGN_PARAGRAPH.RIGHT)

        elif variant == "kp_tp_basic":
            setc(3, _fmt_money(nums["price"]), WD_ALIGN_PARAGRAPH.RIGHT)
            setc(4, _fmt_money(nums["base"]), WD_ALIGN_PARAGRAPH.RIGHT)
            setc(5, _fmt_money(nums["vat_val"]), WD_ALIGN_PARAGRAPH.RIGHT)
            setc(6, _fmt_money(nums["total_val"]), WD_ALIGN_PARAGRAPH.RIGHT)

        else:
            setc(3, _fmt_money(nums["price"]), WD_ALIGN_PARAGRAPH.RIGHT)
            setc(4, _fmt_money(nums["base"]), WD_ALIGN_PARAGRAPH.RIGHT)
            setc(5, _fmt_money(nums["base_after_discount"]), WD_ALIGN_PARAGRAPH.RIGHT)
            setc(6, _fmt_money(nums["vat_val"]), WD_ALIGN_PARAGRAPH.RIGHT)
            setc(7, _fmt_money(nums["total_val"]), WD_ALIGN_PARAGRAPH.RIGHT)

    # итого
    row_cells = table.add_row().cells
    for i, w in enumerate(widths):
        row_cells[i].width = Mm(w)

    _set_cell_text(row_cells[1], "Итого:", bold=True, size_pt=DOCX_TABLE_FONT_PT, align=WD_ALIGN_PARAGRAPH.RIGHT)

    base = float(totals.get("base") or 0.0)
    discount = float(totals.get("discount") or 0.0)
    vat = float(totals.get("vat") or 0.0)
    total = float(totals.get("total") or 0.0)

    if variant == "kp_tp_no_vat_nodiscount":
        _set_cell_text(row_cells[4], _fmt_money(base), bold=True, size_pt=DOCX_TABLE_FONT_PT, align=WD_ALIGN_PARAGRAPH.RIGHT)

    elif variant == "kp_tp_no_vat":
        _set_cell_text(row_cells[4], _fmt_money(base), bold=True, size_pt=DOCX_TABLE_FONT_PT, align=WD_ALIGN_PARAGRAPH.RIGHT)
        _set_cell_text(row_cells[5], _fmt_money(base - discount), bold=True, size_pt=DOCX_TABLE_FONT_PT, align=WD_ALIGN_PARAGRAPH.RIGHT)

    elif variant == "kp_tp_basic":
        _set_cell_text(row_cells[4], _fmt_money(base), bold=True, size_pt=DOCX_TABLE_FONT_PT, align=WD_ALIGN_PARAGRAPH.RIGHT)
        _set_cell_text(row_cells[5], _fmt_money(vat), bold=True, size_pt=DOCX_TABLE_FONT_PT, align=WD_ALIGN_PARAGRAPH.RIGHT)
        _set_cell_text(row_cells[6], _fmt_money(total), bold=True, size_pt=DOCX_TABLE_FONT_PT, align=WD_ALIGN_PARAGRAPH.RIGHT)

    else:
        _set_cell_text(row_cells[4], _fmt_money(base), bold=True, size_pt=DOCX_TABLE_FONT_PT, align=WD_ALIGN_PARAGRAPH.RIGHT)
        _set_cell_text(row_cells[5], _fmt_money(base - discount), bold=True, size_pt=DOCX_TABLE_FONT_PT, align=WD_ALIGN_PARAGRAPH.RIGHT)
        _set_cell_text(row_cells[6], _fmt_money(vat), bold=True, size_pt=DOCX_TABLE_FONT_PT, align=WD_ALIGN_PARAGRAPH.RIGHT)
        _set_cell_text(row_cells[7], _fmt_money(total), bold=True, size_pt=DOCX_TABLE_FONT_PT, align=WD_ALIGN_PARAGRAPH.RIGHT)


def _add_post_table_text(doc: Document, variant: str) -> None:
    if variant not in ("kp_tp_no_vat", "kp_tp_no_vat_nodiscount"):
        return

    lines = [
        "*Цены НДС не облагаются.",
        "1. Гарантийные условия:",
        "- Бесплатная техническая поддержка в течение одного года.",
        "- Бесплатная поставка обновлений в течение одного года.",
        "2. Гибкая система скидок.",
    ]

    for t in lines:
        p = doc.add_paragraph(t)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for r in p.runs:
            r.font.size = Pt(10)

    _add_spacer(doc, 2)


def _add_footer_contacts(doc: Document, context: Dict[str, Any]) -> None:
    manager_name = context.get("manager_name") or "Ответственный за сделку"
    manager_email = context.get("manager_email") or "email ответственного за сделку"
    manager_phone = context.get("manager_phone") or "телефон ответственного за сделку"

    doc.add_paragraph("По любым вопросам и разъяснениям просим обращаться по указанным ниже контактам.")
    _add_spacer(doc, 2)

    p = doc.add_paragraph()
    p.add_run("Подготовил: ").bold = True
    p.add_run(manager_name)

    doc.add_paragraph(f"E-mail: {manager_email}")
    doc.add_paragraph(f"Тел.: {manager_phone}")
    doc.add_paragraph("Web: http://www.primegeo.ru")


def build_docx_for_variant(template_variant: str, context: Dict[str, Any]) -> bytes:
    doc = Document()
    _apply_page_setup(doc)

    lines: List[Dict[str, Any]] = (context.get("lines") or [])
    totals: Dict[str, float] = (context.get("totals") or {})

    _add_header_with_logo(doc, context)
    _add_requisites_block(doc)
    _add_info_block(doc, context)
    _add_valid_until(doc, context)

    _add_center_title(doc, "Бюджет проекта", bold=True, size_pt=11, after_mm=3)

    _add_center_title(
        doc,
        "Состав по обновлению и сопровождению ПО PrimeGeo («ПРАЙМ»)",
        bold=True,
        size_pt=10,
        after_mm=2
    )

    _add_products_table(doc, template_variant, lines, totals)
    _add_spacer(doc, 3)

    _add_post_table_text(doc, template_variant)
    _add_footer_contacts(doc, context)

    out = BytesIO()
    doc.save(out)
    return out.getvalue()
