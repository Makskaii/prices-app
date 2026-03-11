import os
import json
import logging
import traceback
from flask import Blueprint, request, jsonify
import requests

from app.services.bitrix_disk_service import (
    upload_docx_to_disk_replace,
    get_disk_file_detail_url,
    set_deal_kp_link,
    set_quote_kp_link,
    KP_FOLDER_ID
)
from app.docgen_docx import build_docx_for_variant
from app.api.docs import _sanitize_filename

webhook_bp = Blueprint("webhook_bp", __name__)
logger = logging.getLogger(__name__)

BITRIX_WEBHOOK_BASE = os.getenv("BITRIX_WEBHOOK_BASE", "").strip()
if not BITRIX_WEBHOOK_BASE:
    BITRIX_WEBHOOK_BASE = "https://bitrix.primegeo.ru/rest/36/lmhkn7l2tf26204z/"

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
    logger.info(f"Downloading file from: {url}")
    
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    
    filename = "document.docx"
    content_disposition = response.headers.get('Content-Disposition')
    if content_disposition and 'filename=' in content_disposition:
        import re
        filename_match = re.search(r'filename="?([^"]+)"?', content_disposition)
        if filename_match:
            filename = filename_match.group(1)
    
    return response.content, filename

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
        auth_data = data.get("auth", {})

        logger.info(f"Документ {doc_id}, тип сущности {entity_type_id}, ID {entity_id}")

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

        if not download_url:
            return jsonify({"error": "No download URL"}), 400

        logger.info(f"Download URL: {download_url}")

        file_content, original_filename = download_file_from_url(download_url)

        safe_title = _sanitize_filename(doc_title)
        new_filename = f"КП_{safe_title}.docx"

        file_id_disk = upload_docx_to_disk_replace(KP_FOLDER_ID, new_filename, file_content)
        file_url = get_disk_file_detail_url(file_id_disk)

        logger.info(f"File uploaded to disk, URL: {file_url}")

        if entity_type == "DEAL":
            set_deal_kp_link(int(entity_id), file_url)
            logger.info(f"Link saved to deal {entity_id}")
        else:
            set_quote_kp_link(int(entity_id), file_url)
            logger.info(f"Link saved to quote {entity_id}")

        return jsonify({"success": True}), 200

    except Exception as e:
        logger.exception("Ошибка обработки вебхука")
        return jsonify({"error": str(e)}), 500