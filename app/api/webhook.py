import os
import json
import logging
import traceback
import re
from flask import Blueprint, request, jsonify
import requests

from app.services.bitrix_disk_service import (
    upload_docx_to_disk_replace,
    get_disk_file_detail_url,
    set_deal_kp_link,
    set_quote_kp_link,
)

webhook_bp = Blueprint("webhook_bp", __name__)

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
        "name_prefix": "КП_"
    },
    "contract": {
        "folder_id": CONTRACT_FOLDER_ID,
        "deal_field": "UF_CRM_1773241796610",
        "deal_field_camel": "ufCrm_1773241796610",
        "name_prefix": "Договор_"
    }
}

def bx_call(method: str, params: dict, auth_token: str = None) -> dict:
    url = f"{BITRIX_WEBHOOK_BASE.rstrip('/')}/{method}.json"
    
    headers = {}
    if auth_token:
        headers['Authorization'] = f'Bearer {auth_token}'
    
    response = requests.post(url, json=params, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise Exception(f"Bitrix error: {data.get('error_description') or data.get('error')}")
    return data.get("result")

def parse_bitrix_webhook(form_data):
    result = {}
    for key, value in form_data.items():
        parts = key.replace(']', '').split('[')
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
    content_disposition = response.headers.get('Content-Disposition')
    if content_disposition and 'filename=' in content_disposition:
        filename_match = re.search(r'filename="?([^"]+)"?', content_disposition)
        if filename_match:
            filename = filename_match.group(1)
    
    return response.content, filename

def detect_document_type(title: str, template_id: str = None):
    
    if template_id:
        template_config = {
            "38": "kp",
            "39": "kp",
            "40": "contract",
            "41": "contract"
        }
        if template_id in template_config:
            return template_config[template_id]
    
    title_lower = title.lower()
    
    contract_markers = ["договор", "контракт", "contract" "поставка"]
    for marker in contract_markers:
        if marker in title_lower:
            return "contract"
    
    kp_markers = ["коммерческое", "предложение", "кп", "kp"]
    for marker in kp_markers:
        if marker in title_lower:
            return "kp"
    
    return None

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
            "1": "LEAD", "2": "DEAL", "3": "CONTACT", "4": "COMPANY", "7": "QUOTE"
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
        template_id = str(document.get("templateId", ""))

        if not download_url:
            return jsonify({"error": "No download URL"}), 400

        doc_type = detect_document_type(doc_title, template_id)
        
        if doc_type is None:
            return jsonify({
                "status": "skipped", 
                "reason": "unknown_document_type",
                "title": doc_title
            }), 200

        doc_config = DOCUMENT_TYPES.get(doc_type)
        
        if doc_config["folder_id"] is None:
            return jsonify({"error": f"Folder ID not configured for {doc_type}"}), 500

        owner_id = 10
        file_content, original_filename = download_file_from_url(download_url)

        safe_title = "".join(c for c in doc_title if c.isalnum() or c in " .-_()").strip()
        if not safe_title:
            safe_title = f"document_{doc_id}"
        new_filename = f"{doc_config['name_prefix']}{safe_title}.docx"

        file_id_disk = upload_docx_to_disk_replace(
            doc_config["folder_id"], 
            new_filename, 
            file_content,
            created_by=owner_id
        )
        file_url = get_disk_file_detail_url(file_id_disk)

        if entity_type == "DEAL":
            set_deal_kp_link(int(entity_id), file_url, doc_config["deal_field"])
        else:
            set_quote_kp_link(int(entity_id), file_url, doc_config["deal_field_camel"])

        return jsonify({"success": True}), 200

    except Exception as e:
        print(f"Webhook error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@webhook_bp.route("/run-initials-job", methods=["GET"])
def run_initials_job_endpoint():
    """Эндпоинт для запуска обработчика инициалов"""
    try:
        from app.handlers.initials_job import run
        run()
        return jsonify({"success": True, "message": "Job completed"}), 200
    except Exception as e:
        logger.error(f"Ошибка в эндпоинте run-initials-job: {e}")
        return jsonify({"error": str(e)}), 500