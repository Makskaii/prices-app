# app/services/bitrix_api.py
import os
import requests
from datetime import datetime, timedelta
from calendar import monthrange

BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK_URL")

SESSION = requests.Session()


def _request(method: str, url: str, params: dict | None = None, http_method: str = "POST"):
    if http_method.upper() == "GET":
        response = SESSION.get(url, params=params, timeout=20)
    else:
        response = SESSION.post(url, json=params or {}, timeout=20)

    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise Exception(f"Bitrix24 error: {data.get('error_description') or data['error']}")

    return data


def bitrix_call_raw(method: str, params: dict | None = None, http_method: str = "POST"):
    """
    Низкоуровневый вызов: возвращает полный JSON от Bitrix (с полем result).
    """
    if not BITRIX_WEBHOOK:
        raise RuntimeError("ENV var BITRIX_WEBHOOK_URL is not set")

    url = f"{BITRIX_WEBHOOK}/{method}"
    return _request(method, url, params, http_method)


def bitrix_call(method: str, params: dict | None = None, http_method: str = "POST"):
    """
    Вызов, который сразу возвращает data["result"].
    """
    data = bitrix_call_raw(method, params, http_method)
    return data.get("result")


def bitrix_call_paginated(method: str, params: dict | None = None, http_method: str = "POST"):
    """
    Вызов для методов Bitrix с постраничной выдачей (crm.deal.list, crm.product.list и т.п.).
    Собирает все страницы в один список.
    """
    params = params.copy() if params else {}
    start = 0
    all_items = []

    while True:
        params["start"] = start
        response = bitrix_call_raw(method, params, http_method)

        items = response.get("result", []) or []
        all_items.extend(items)

        next_start = response.get("next")
        if next_start is None:
            break

        start = next_start

    return all_items


# ========= Дальше новые функции для работы со сделкой / контактами / пользователем =========

class BitrixError(Exception):
    """Наш обёрточный тип исключения для удобства обработки ошибок."""
    pass


def _first_multivalue(values: list | None, field: str = "VALUE") -> str | None:
    """
    Берёт первый элемент из мультиполя (PHONE, EMAIL) и возвращает values[0][field].
    """
    if not values:
        return None
    if not isinstance(values, list):
        return None
    first = values[0] or {}
    return first.get(field) or None


def _add_months(dt: datetime, months: int) -> datetime:
    """
    Прибавить к дате N месяцев, аккуратно учитывая длину месяца.
    """
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def get_deal_full_info(deal_id: str | int) -> dict:
    """
    Возвращает словарь с нужными нам данными по сделке:

    {
        "company_name": ...,
        "contact_name": ...,
        "contact_email": ...,
        "contact_phone": ...,
        "offer_date": "ДД.ММ.ГГГГ",
        "offer_valid_until": "ДД.ММ.ГГГГ",
        "manager_name": ...,
        "manager_email": ...,
        "manager_phone": ...
    }
    """
    try:
        # 1. Сама сделка
        deal = bitrix_call("crm.deal.get", {"id": deal_id})
    except Exception as e:
        raise BitrixError(f"Ошибка получения сделки {deal_id}: {e}") from e

    if not deal:
        raise BitrixError(f"Сделка {deal_id} не найдена")

    # --- Компания/контакт из сделки ---
    company_name = deal.get("COMPANY_TITLE") or deal.get("TITLE") or ""

    contact_id = deal.get("CONTACT_ID")
    if not contact_id:
        # иногда контакты в CONTACT_IDS
        contact_ids = deal.get("CONTACT_IDS") or []
        if isinstance(contact_ids, list) and contact_ids:
            contact_id = contact_ids[0]

    contact = {}
    if contact_id:
        try:
            contact = bitrix_call("crm.contact.get", {"id": contact_id}) or {}
        except Exception as e:
            # не критично, просто оставим пусто
            raise BitrixError(f"Ошибка получения контакта {contact_id}: {e}") from e

    # ФИО контакта
    contact_name = " ".join([
        (contact.get("LAST_NAME") or "").strip(),
        (contact.get("NAME") or "").strip(),
        (contact.get("SECOND_NAME") or "").strip(),
    ]).strip() or ""

    # email/телефон контакта
    contact_email = _first_multivalue(contact.get("EMAIL")) or ""
    contact_phone = _first_multivalue(contact.get("PHONE")) or ""

    # --- Ответственный менеджер ---
    manager_id = deal.get("ASSIGNED_BY_ID")
    manager = {}
    if manager_id:
        try:
            manager = bitrix_call("user.get", {"ID": manager_id}) or {}
        except Exception as e:
            raise BitrixError(f"Ошибка получения пользователя {manager_id}: {e}") from e

    manager_name = " ".join([
        (manager.get("LAST_NAME") or "").strip(),
        (manager.get("NAME") or "").strip(),
        (manager.get("SECOND_NAME") or "").strip(),
    ]).strip() or ""

    manager_email = manager.get("EMAIL") or ""
    # пробуем рабочий телефон, потом мобильный
    manager_phone = (
        manager.get("WORK_PHONE")
        or manager.get("PERSONAL_MOBILE")
        or manager.get("PERSONAL_PHONE")
        or ""
    )

    # --- Даты: дата создания сделки и +3 месяца ---
    raw_created = deal.get("DATE_CREATE")  # например "2025-12-11T09:45:00+03:00"
    offer_date_str = ""
    offer_valid_until_str = ""

    if raw_created:
        try:
            # приводим к isoformat, если без таймзоны
            # Bitrix чаще всего отдаёт уже корректный ISO
            dt = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
        except Exception:
            dt = None

        if dt:
            offer_date_str = dt.strftime("%d.%m.%Y")
            valid_dt = _add_months(dt, 3)
            offer_valid_until_str = valid_dt.strftime("%d.%m.%Y")

    return {
        "company_name": company_name,
        "contact_name": contact_name,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "offer_date": offer_date_str,
        "offer_valid_until": offer_valid_until_str,
        "manager_name": manager_name,
        "manager_email": manager_email,
        "manager_phone": manager_phone,
    }

# ====== Высокоуровневая выборка сделки + контакт + ответственный ======


def _extract_contact_email(contact: dict | None) -> str | None:
    """
    Вытаскивает первый нормальный email из массива EMAIL у контакта.
    Формат обычно: {"TYPE_ID": "EMAIL", "VALUE": "...", "VALUE_TYPE": "WORK"}.
    """
    if not contact:
        return None
    emails = contact.get("EMAIL") or []
    if not isinstance(emails, list):
        return None

    preferred = None
    for e in emails:
        if not isinstance(e, dict):
            continue
        val = e.get("VALUE")
        if not val:
            continue
        if e.get("VALUE_TYPE") == "WORK":
            return val
        if preferred is None:
            preferred = val
    return preferred


def _extract_user_phone(user: dict | None) -> str | None:
    """
    Пробуем достать телефон ответственного.
    """
    if not user:
        return None

    for key in ("WORK_PHONE", "PERSONAL_MOBILE", "PERSONAL_PHONE"):
        val = user.get(key)
        if val:
            return val
    return None


def fetch_deal_with_extras(deal_id: int) -> dict:
   
    if not BITRIX_WEBHOOK:
        raise RuntimeError("BITRIX_WEBHOOK_URL is not set")

    # ---- 1. Получаем сделку ----
    deal = bitrix_call("crm.deal.get", {"id": deal_id}, http_method="GET") or {}

    result: dict = {
        "deal_title": (deal.get("TITLE") or "").strip(),
        "deal_company": None,
        "company_id": None,
        "contact_name": None,
        "contact_email": None,
        "manager_name": None,
        "manager_email": None,
        "manager_phone": None,
        "offer_date": None,
        "valid_until": None,
    }

        # ---- 2. Компания / имя контрагента ----
    company_title = None
    company_id = deal.get("COMPANY_ID")
    if company_id:
        try:
            company = bitrix_call("crm.company.get", {"id": company_id}, http_method="GET") or {}
            company_title = company.get("TITLE")
        except Exception:
            company_title = None

    result["deal_company"] = company_title
    result["company_id"] = str(company_id) if company_id else None



    # ---- 3. Контакт ----
    contact_fio = None
    contact_email = None
    contact_id = deal.get("CONTACT_ID")

    if contact_id:
        try:
            contact = bitrix_call("crm.contact.get", {"id": contact_id}, http_method="GET") or {}
            first_name = contact.get("NAME") or ""
            last_name = contact.get("LAST_NAME") or ""
            second_name = contact.get("SECOND_NAME") or ""

            fio_parts = [p for p in (last_name, first_name, second_name) if p]
            contact_fio = " ".join(fio_parts) if fio_parts else None

            contact_email = _extract_contact_email(contact)

        except Exception:
            contact_fio = None
            contact_email = None

    result["contact_name"] = contact_fio
    result["contact_email"] = contact_email

    # ---- 4. Ответственный менеджер ----
    manager_name = None
    manager_email = None
    manager_phone = None

    assigned_id = deal.get("ASSIGNED_BY_ID")
    if assigned_id:
        try:
            # Для вебхуков Bitrix метод user.get обычно возвращает список пользователей
            users = bitrix_call("user.get", {"ID": assigned_id}, http_method="GET") or []
            user = users[0] if isinstance(users, list) and users else None
            if user:
                uf = user.get("NAME") or ""
                ul = user.get("LAST_NAME") or ""
                up = user.get("SECOND_NAME") or ""

                fio_parts = [p for p in (ul, uf, up) if p]
                manager_name = " ".join(fio_parts) if fio_parts else None

                manager_email = user.get("EMAIL") or None
                manager_phone = _extract_user_phone(user)
        except Exception:
            # В твоём случае тут может быть 401 — просто не будем падать
            current_app.logger.warning("Bitrix: не удалось получить пользователя %s: %s", assigned_id, e)
            manager_name = None
            manager_email = None
            manager_phone = None

    result["manager_name"] = manager_name
    result["manager_email"] = manager_email
    result["manager_phone"] = manager_phone

    # ---- 5. Дата КП и срок действия ----
    # Берём либо BEGINDATE, либо DATE_CREATE
    raw_date = deal.get("BEGINDATE") or deal.get("DATE_CREATE")

    offer_date_str = None
    valid_until_str = None

    if raw_date:
        # Обычно "YYYY-MM-DDTHH:MM:SS+03:00", берём первые 10 символов
        base = raw_date[:10]
        dt = None
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                dt = datetime.strptime(base, fmt)
                break
            except Exception:
                continue

        if dt is None:
            dt = datetime.utcnow()

        d = dt.date()
        offer_date_str = d.strftime("%d.%m.%Y")
        valid_until_str = (d + timedelta(days=90)).strftime("%d.%m.%Y")

    result["offer_date"] = offer_date_str
    result["valid_until"] = valid_until_str

    return result
