import os
import sys
import time
import logging
from datetime import datetime
import calendar

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.bitrix_api import bitrix_call, bitrix_call_paginated

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

QUOTE_DATE_FIELD = "ufCrm_QUOTE_1773390831247"

def get_russian_month(month_num):
    months = {1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня", 7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"}
    return months.get(month_num, "")

def add_months(source_date, months):
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, calendar.monthrange(year, month)[1])
    return source_date.replace(year=year, month=month, day=day)

def format_date_russian(date_obj):
    return f"{date_obj.day} {get_russian_month(date_obj.month)} {date_obj.year}"

def get_all_quote_ids():
    quote_ids = []
    start = 0
    
    while True:
        try:
            result = bitrix_call("crm.item.list", {
                "entityTypeId": 7,
                "select": ["id"],
                "start": start
            })
            
            items = []
            if isinstance(result, list):
                items = result
            elif isinstance(result, dict):
                items = result.get("items", [])
            
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    quote_ids.append(item["id"])
                elif isinstance(item, (int, str)):
                    quote_ids.append(str(item))
            
            if len(items) < 50:
                break
                
            start += 50
            
        except Exception as e:
            logger.error(f"Ошибка при получении списка: {e}")
            break
    
    return quote_ids

def process_quote(quote_id):
    try:
        today = datetime.now().date()
        future_date = add_months(today, 3)
        formatted_date = format_date_russian(future_date)
        
        quote = bitrix_call("crm.item.get", {"entityTypeId": 7, "id": quote_id})
        
        if not quote:
            return False
        
        item = None
        if isinstance(quote, dict):
            if "item" in quote:
                item = quote["item"]
            else:
                item = quote
        
        if not item:
            return False
        
        current_value = item.get(QUOTE_DATE_FIELD)
        
        if current_value == formatted_date:
            return False
        
        bitrix_call("crm.item.update", {
            "entityTypeId": 7,
            "id": quote_id,
            "fields": {QUOTE_DATE_FIELD: formatted_date}
        })
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка обработки предложения {quote_id}: {e}")
        return False

def run():
    try:
        quote_ids = get_all_quote_ids()
        
        if not quote_ids:
            return
        
        for quote_id in quote_ids:
            process_quote(quote_id)
            time.sleep(0.2)
            
    except Exception as e:
        logger.error(f"Ошибка: {e}")