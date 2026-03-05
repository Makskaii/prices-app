# api/bitrix.py
from flask import Blueprint, request, jsonify
import requests
import json
import os

bitrix_bp = Blueprint("bitrix_bp", __name__)

BITRIX_WEBHOOK = os.getenv(
    "BITRIX_WEBHOOK_URL",
    "https://bitrix.primegeo.ru/rest/36/lmhkn7l2tf26204z"
).rstrip("/")

# Поля состояния (CRM custom fields)
DEAL_STATE_FIELD = os.getenv("DEAL_STATE_FIELD", "UF_CRM_1764667329")
QUOTE_STATE_FIELD = os.getenv("QUOTE_STATE_FIELD", "ufCrm_QUOTE_1769692749969")

import logging

logger = logging.getLogger("bitrix_sync")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def jdump(data):
    # гарантируем строку JSON без экранирования кириллицы
    return json.dumps(data, ensure_ascii=False)

def jload(s: str):
    if not s:
        return {}
    if isinstance(s, (dict, list)):
        # иногда состояние могут уже отдать объектом (маловероятно, но на всякий)
        return s
    try:
        return json.loads(s)
    except Exception:
        return {}

def bx_post(method: str, payload: dict, timeout: int = 20) -> dict:
    url = f"{BITRIX_WEBHOOK}/{method}.json"
    r = requests.post(url, json=payload, timeout=timeout)

    if r.status_code != 200:
        raise RuntimeError(f"Bitrix HTTP {r.status_code}: {r.text}")

    resp = r.json()
    if isinstance(resp, dict) and resp.get("error"):
        raise RuntimeError(resp.get("error_description") or resp.get("error") or "Bitrix error")

    return resp


@bitrix_bp.route("/bx/load", methods=["GET", "POST"])
def load_from_bitrix():
    """
    Возвращает состояние приложения из CRM, чтобы ВСЕ пользователи видели одинаковую таблицу.
    Можно дергать GET ?mode=DEAL&id=123 или POST {mode,id}
    """
    if request.method == "GET":
        mode = (request.args.get("mode") or "").upper()  # DEAL | QUOTE
        entity_id = str(request.args.get("id") or "")
    else:
        data = request.get_json(silent=True) or {}
        mode = (data.get("mode") or "").upper()
        entity_id = str(data.get("id") or "")

    if not entity_id.isdigit():
        return jsonify({"ok": False, "error": "Invalid entity id"}), 400

    try:
        # ---------------- QUOTE ----------------
        if mode == "QUOTE":
            payload = {
                "entityTypeId": 7,
                "id": int(entity_id)
            }
            resp = bx_post("crm.item.get", payload, timeout=20)
            item = (resp.get("result") or {}).get("item") or {}
            raw_state = item.get(QUOTE_STATE_FIELD) or ""
            state = jload(raw_state)

            # вернем ещё opportunity для сверки
            opportunity = item.get("opportunity")

            return jsonify({
                "ok": True,
                "mode": "QUOTE",
                "id": int(entity_id),
                "state": state,
                "rawState": raw_state,   # удобно для дебага, можно убрать позже
                "sumTotal": opportunity
            })

        # ---------------- DEAL ----------------
        if mode == "DEAL":
            payload = {"id": int(entity_id)}
            resp = bx_post("crm.deal.get", payload, timeout=20)
            deal = resp.get("result") or {}
            raw_state = deal.get(DEAL_STATE_FIELD) or ""
            state = jload(raw_state)

            opportunity = deal.get("OPPORTUNITY")

            return jsonify({
                "ok": True,
                "mode": "DEAL",
                "id": int(entity_id),
                "state": state,
                "rawState": raw_state,   # удобно для дебага, можно убрать позже
                "sumTotal": opportunity
            })

        return jsonify({"ok": False, "error": "Unknown mode"}), 400

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

@bitrix_bp.route("/bx/save", methods=["POST"])
def save_to_bitrix():
    try:
        data = request.get_json(force=True)

        logger.info("=== BX SAVE START ===")
        logger.info(f"Incoming data: {data}")

        mode = (data.get("mode") or "").upper()
        entity_id = data.get("id")
        state = data.get("state") or {}
        sum_total = float(data.get("sumTotal") or 0)

        if not entity_id:
            return jsonify({"ok": False, "error": "Missing entity id"}), 400

        lines = state.get("lines") or []
        rows = []

        for index, line in enumerate(lines, start=1):
            try:
                quantity = float(line.get("quantity") or 0)
                price_app = float(line.get("price") or 0)
                discount_rate = float(line.get("discountPercent") or 0)
                vat_rate = float(line.get("vatPercent") or 0)

                # Считаем итоговую цену с учетом скидки
                total_price = price_app * quantity * (1 - discount_rate / 100)
                # Добавляем НДС
                total_price_with_vat = round(total_price * (1 + vat_rate / 100), 2)

                row = {
                    "productId": int(line.get("productId")),
                    "price": total_price_with_vat,  # передаем сумму с НДС
                    "quantity": quantity,
                    "discountTypeId": 2,
                    "discountRate": discount_rate,
                    "taxRate": vat_rate,
                    "sort": index * 10
                }

                logger.info(f"Prepared row #{index}: {row}")
                rows.append(row)

            except Exception as e:
                logger.error(f"Row error: {e}")

        logger.info(f"Final rows payload: {rows}")

        # ---------------- DEAL ----------------
        if mode == "DEAL":
            bx_post("crm.deal.update", {
                "id": int(entity_id),
                "fields": {
                    DEAL_STATE_FIELD: jdump(state),
                    "OPPORTUNITY": sum_total
                }
            }, timeout=20)

            product_response = bx_post("crm.item.productrow.set", {
                "ownerType": "D",
                "ownerId": int(entity_id),
                "productRows": rows
            }, timeout=20)

            logger.info(f"Product rows response: {product_response}")
            logger.info("=== BX SAVE END ===")
            return jsonify({"ok": True})

        # ---------------- QUOTE ----------------
        if mode == "QUOTE":
            bx_post("crm.quote.update", {
                "id": int(entity_id),
                "fields": {
                    QUOTE_STATE_FIELD: jdump(state),
                    "OPPORTUNITY": sum_total
                }
            }, timeout=20)

            product_response = bx_post("crm.item.productrow.set", {
                "ownerType": "Q",
                "ownerId": int(entity_id),
                "productRows": rows
            }, timeout=20)

            logger.info(f"Product rows response: {product_response}")
            logger.info("=== BX SAVE END ===")
            return jsonify({"ok": True})

        return jsonify({"ok": False, "error": "Unsupported mode"}), 400

    except Exception as e:
        logger.exception("Fatal error in save_to_bitrix")
        return jsonify({"ok": False, "error": str(e)}), 500
