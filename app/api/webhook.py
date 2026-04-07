import os
import logging
import re
import requests
from flask import Blueprint, request, jsonify

from app.services.bitrix_disk_service import (
    upload_docx_to_disk_replace,
    get_disk_file_detail_url,
    set_deal_kp_link,
    set_quote_kp_link,
)

webhook_bp = Blueprint("webhook_bp", __name__)
logger = logging.getLogger(__name__)
logging.getLogger("app.api.webhook").setLevel(logging.CRITICAL)

BITRIX_WEBHOOK_BASE = os.getenv("BITRIX_WEBHOOK_BASE", "").strip()
if not BITRIX_WEBHOOK_BASE:
    BITRIX_WEBHOOK_BASE = "https://bitrix.primegeo.ru/rest/36/lmhkn7l2tf26204z/"

KP_FOLDER_ID = 316
CONTRACT_FOLDER_ID = 1199

DOCUMENT_TYPES = {
    "kp": {
        "folder_id": KP_FOLDER_ID,
        "deal_field": "UF_CRM_697C815A3D688",
        "deal_field_camel": "ufCrm_697C815A3D688",
    },
    "contract": {
        "folder_id": CONTRACT_FOLDER_ID,
        "deal_field": "UF_CRM_1773241796610",
        "deal_field_camel": "ufCrm_1773241796610",
    },
}

TEMPLATE_TYPE_MAP = {
    "38": "kp",
    "39": "kp",
    "40": "contract",
    "41": "contract",
}


def bx_call(method: str, params: dict, auth_token: str = None) -> dict:
    url = f"{BITRIX_WEBHOOK_BASE.rstrip('/')}/{method}.json"
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    response = requests.post(url, json=params, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise Exception(f"Bitrix error: {data.get('error_description') or data.get('error')}")
    return data.get("result")


def parse_bitrix_webhook(form_data):
    result = {}
    for key, value in form_data.items():
        parts = key.replace("]", "").split("[")
        current = result
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                current[part] = value
            else:
                if part not in current:
                    current[part] = {}
                current = current[part]
    return result


def download_file_from_url(url: str) -> tuple[bytes, str]:
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    filename = "document.docx"
    content_disposition = response.headers.get("Content-Disposition")
    if content_disposition and "filename=" in content_disposition:
        filename_match = re.search(r'filename="?([^"]+)"?', content_disposition)
        if filename_match:
            filename = filename_match.group(1)

    return response.content, filename


def detect_document_type(title: str, template_id: str = None):
    if template_id and template_id in TEMPLATE_TYPE_MAP:
        return TEMPLATE_TYPE_MAP[template_id]

    title_lower = (title or "").lower()

    contract_markers = ["договор", "контракт", "contract"]
    for marker in contract_markers:
        if marker in title_lower:
            return "contract"

    kp_markers = ["коммерческое", "предложение", "кп", "kp"]
    for marker in kp_markers:
        if marker in title_lower:
            return "kp"

    return None


def sanitize_filename_part(value: str, fallback: str, max_length: int = 120) -> str:
    value = str(value or "").strip()
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" ._")
    value = value[:max_length].strip(" ._")
    return value or fallback


def get_entity_title(entity_type: str, entity_id: int) -> str:
    if entity_type == "DEAL":
        entity = bx_call("crm.deal.get", {"id": int(entity_id)})
        return entity.get("TITLE") or f"deal_{entity_id}"

    if entity_type == "QUOTE":
        entity = bx_call("crm.quote.get", {"id": int(entity_id)})
        return entity.get("TITLE") or f"quote_{entity_id}"

    return f"entity_{entity_id}"


def get_template_name(document: dict, template_id: str) -> str:
    direct_name = (
        document.get("templateTitle")
        or document.get("templateName")
        or document.get("template")
    )
    if isinstance(direct_name, str) and direct_name.strip():
        return direct_name.strip()

    if template_id:
        template_info = bx_call("crm.documentgenerator.template.get", {"id": int(template_id)})
        if isinstance(template_info, dict):
            template = template_info.get("template") if isinstance(template_info.get("template"), dict) else template_info
            template_name = template.get("name")
            if template_name:
                return template_name

    return f"template_{template_id}" if template_id else "template"


def build_filename(entity_title: str, template_name: str) -> str:
    safe_entity_title = sanitize_filename_part(entity_title, "entity")
    safe_template_name = sanitize_filename_part(template_name, "template")
    filename = f"{safe_entity_title}_{safe_template_name}.docx"
    if len(filename) > 240:
        overflow = len(filename) - 240
        safe_entity_title = safe_entity_title[:-overflow].rstrip(" ._") or "entity"
        filename = f"{safe_entity_title}_{safe_template_name}.docx"
    return filename


def save_file_link(entity_type: str, entity_id: int, file_url: str, doc_type: str):
    doc_config = DOCUMENT_TYPES.get(doc_type, DOCUMENT_TYPES["kp"])

    if entity_type == "DEAL":
        set_deal_kp_link(int(entity_id), file_url, doc_config["deal_field"])
    else:
        set_quote_kp_link(int(entity_id), file_url, doc_config["deal_field_camel"])


@webhook_bp.route("/bitrix-webhook", methods=["POST"])
def handle_bitrix_webhook():
    try:
        form_data = request.form.to_dict()
        data = parse_bitrix_webhook(form_data)

        event = data.get("event")
        if event != "ONCRMDOCUMENTGENERATORDOCUMENTADD":
            return jsonify({"status": "ignored", "event": event}), 200

        fields = data.get("data", {}).get("FIELDS", {})
        doc_id = fields.get("ID")
        entity_type_id = fields.get("ENTITY_TYPE_ID")
        entity_id = fields.get("ENTITY_ID")

        entity_type_map = {
            "1": "LEAD",
            "2": "DEAL",
            "3": "CONTACT",
            "4": "COMPANY",
            "7": "QUOTE",
        }
        entity_type = entity_type_map.get(str(entity_type_id), "UNKNOWN")

        if entity_type not in ["DEAL", "QUOTE"]:
            return jsonify({"status": "skipped"}), 200

        doc_info = bx_call("crm.documentgenerator.document.get", {"id": doc_id})
        if not doc_info or "document" not in doc_info:
            return jsonify({"error": "Document not found"}), 404

        document = doc_info["document"]
        download_url = document.get("downloadUrlMachine") or document.get("downloadUrl")
        doc_title = document.get("title", f"document_{doc_id}")
        template_id = str(document.get("templateId", "") or "")

        if not download_url:
            return jsonify({"error": "No download URL"}), 400

        doc_type = detect_document_type(doc_title, template_id)
        if doc_type is None:
            return jsonify(
                {
                    "status": "skipped",
                    "reason": "unknown_document_type",
                    "title": doc_title,
                }
            ), 200

        doc_config = DOCUMENT_TYPES.get(doc_type)
        if doc_config["folder_id"] is None:
            return jsonify({"error": f"Folder ID not configured for {doc_type}"}), 500

        owner_id = 10
        file_content, _ = download_file_from_url(download_url)

        entity_title = get_entity_title(entity_type, int(entity_id))
        template_name = get_template_name(document, template_id)
        new_filename = build_filename(entity_title, template_name)

        file_id_disk = upload_docx_to_disk_replace(
            doc_config["folder_id"],
            new_filename,
            file_content,
            created_by=owner_id,
        )
        file_url = get_disk_file_detail_url(file_id_disk)

        save_file_link(entity_type, int(entity_id), file_url, doc_type)

        return jsonify({
            "success": True,
            "filename": new_filename,
            "doc_type": doc_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "template_id": template_id,
        }), 200

    except Exception as e:
        logger.exception("Webhook error")
        return jsonify({"error": str(e)}), 500


@webhook_bp.route("/run-initials-job", methods=["GET"])
def run_initials_job_endpoint():
    try:
        from app.handlers.initials_job import run

        run()
        return jsonify({"success": True, "message": "Job completed"}), 200
    except Exception as e:
        logger.exception("Ошибка в эндпоинте run-initials-job")
        return jsonify({"error": str(e)}), 500
