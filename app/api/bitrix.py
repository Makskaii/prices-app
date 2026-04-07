from flask import Blueprint, request, jsonify
import requests
import json
import os
import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

bitrix_bp = Blueprint("bitrix_bp", __name__)

BITRIX_WEBHOOK = os.getenv(
    "BITRIX_WEBHOOK_URL",
    "https://bitrix.primegeo.ru/rest/36/lmhkn7l2tf26204z"
).rstrip("/")

DEAL_STATE_FIELD = os.getenv("DEAL_STATE_FIELD", "UF_CRM_1764667329")
QUOTE_STATE_FIELD = os.getenv("QUOTE_STATE_FIELD", "ufCrm_QUOTE_1769692749969")

logger = logging.getLogger("bitrix_sync")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def jdump(data):
    return json.dumps(data, ensure_ascii=False)


def jload(s):
    if not s:
        return {}
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except Exception:
        return {}


def to_decimal(value, default="0"):
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def q2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q6(value):
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def bx_number(value, places=6):
    if places == 2:
        return format(q2(value), "f")
    return format(q6(value), "f")


def bx_post(method, payload, timeout=20):
    url = f"{BITRIX_WEBHOOK}/{method}.json"
    r = requests.post(url, json=payload, timeout=timeout)

    if r.status_code != 200:
        raise RuntimeError(f"Bitrix HTTP {r.status_code}: {r.text}")

    resp = r.json()
    if isinstance(resp, dict) and resp.get("error"):
        raise RuntimeError(resp.get("error_description") or resp.get("error") or "Bitrix error")

    return resp


def build_product_rows(lines):
    rows = []

    for index, line in enumerate(lines, start=1):
        try:
            product_id_raw = line.get("productId")
            if not product_id_raw:
                logger.warning(f"Skipped row #{index}: missing productId")
                continue

            quantity = to_decimal(line.get("quantity"), "0")
            base_price = to_decimal(line.get("price"), "0")
            discount_rate = to_decimal(line.get("discountPercent"), "0")
            vat_rate = to_decimal(line.get("vatPercent"), "0")

            discount_multiplier = Decimal("1") - (discount_rate / Decimal("100"))
            vat_multiplier = Decimal("1") + (vat_rate / Decimal("100"))

            price_for_bitrix = base_price * discount_multiplier * vat_multiplier
            price_for_bitrix = q6(price_for_bitrix)

            row = {
                "productId": int(product_id_raw),
                "price": bx_number(price_for_bitrix, 6),
                "quantity": bx_number(quantity, 6),
                "discountTypeId": 2,
                "discountRate": bx_number(discount_rate, 2),
                "taxRate": bx_number(vat_rate, 2),
                "taxIncluded": "N",
                "sort": index * 10
            }

            logger.info(
                f"Prepared row #{index}: "
                f"base_price={base_price}, "
                f"price_for_bitrix={price_for_bitrix}, "
                f"quantity={quantity}, "
                f"discount={discount_rate}, "
                f"vat={vat_rate}, "
                f"row={row}"
            )

            rows.append(row)

        except Exception as e:
            logger.exception(f"Row error #{index}: {e}")

    return rows


@bitrix_bp.route("/bx/load", methods=["GET", "POST"])
def load_from_bitrix():
    if request.method == "GET":
        mode = (request.args.get("mode") or "").upper()
        entity_id = str(request.args.get("id") or "")
    else:
        data = request.get_json(silent=True) or {}
        mode = (data.get("mode") or "").upper()
        entity_id = str(data.get("id") or "")

    if not entity_id.isdigit():
        return jsonify({"ok": False, "error": "Invalid entity id"}), 400

    try:
        if mode == "QUOTE":
            payload = {
                "entityTypeId": 7,
                "id": int(entity_id)
            }
            resp = bx_post("crm.item.get", payload, timeout=20)
            item = (resp.get("result") or {}).get("item") or {}
            raw_state = item.get(QUOTE_STATE_FIELD) or ""
            state = jload(raw_state)
            opportunity = item.get("opportunity")

            return jsonify({
                "ok": True,
                "mode": "QUOTE",
                "id": int(entity_id),
                "state": state,
                "rawState": raw_state,
                "sumTotal": opportunity
            })

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
                "rawState": raw_state,
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
        sum_total = q2(to_decimal(data.get("sumTotal"), "0"))

        if not entity_id:
            return jsonify({"ok": False, "error": "Missing entity id"}), 400

        lines = state.get("lines") or []
        rows = build_product_rows(lines)

        logger.info(f"Final rows payload: {rows}")

        if mode == "DEAL":
            bx_post("crm.deal.update", {
                "id": int(entity_id),
                "fields": {
                    DEAL_STATE_FIELD: jdump(state),
                    "OPPORTUNITY": bx_number(sum_total, 2)
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

        if mode == "QUOTE":
            quote_update_response = bx_post("crm.item.update", {
                "entityTypeId": 7,
                "id": int(entity_id),
                "fields": {
                    QUOTE_STATE_FIELD: jdump(state),
                    "opportunity": bx_number(sum_total, 2)
                }
            }, timeout=20)

            product_response = bx_post("crm.item.productrow.set", {
                "ownerType": "Q",
                "ownerId": int(entity_id),
                "productRows": rows
            }, timeout=20)

            logger.info(f"Quote update response: {quote_update_response}")
            logger.info(f"Product rows response: {product_response}")
            logger.info("=== BX SAVE END ===")
            return jsonify({"ok": True})

        return jsonify({"ok": False, "error": "Unsupported mode"}), 400

    except Exception as e:
        logger.exception("Fatal error in save_to_bitrix")
        return jsonify({"ok": False, "error": str(e)}), 500