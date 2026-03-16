# app/handlers/initials_job.py
import os
import sys
import time
import logging
from datetime import datetime

# Добавляем путь к корню проекта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.bitrix_api import bitrix_call, bitrix_call_paginated

# Настройка логирования только в stdout (для systemd)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Стадии для обработки
DEAL_STAGES = [
    "UC_YA4B3S",     # Договор согласован
    "FINAL_INVOICE", # Финальный счет
    "PREPARATION"    # Подготовка
]

INITIAL_FIELD = "UF_CRM_1773323936974"

def get_contact_info(contact_id):
    """Получает информацию о контакте, включая отчество"""
    if not contact_id:
        return None
    
    try:
        contact = bitrix_call("crm.contact.get", {"id": contact_id})
        if not contact:
            return None
        
        # Безопасно получаем отчество
        second_name = contact.get("SECOND_NAME")
        if second_name is None:
            second_name = ""
        else:
            second_name = str(second_name).strip()
        
        return {
            "second_name": second_name,
            "name": contact.get("NAME", ""),
            "last_name": contact.get("LAST_NAME", "")
        }
    except Exception as e:
        logger.error(f"Ошибка получения контакта {contact_id}: {e}")
        return None

def get_initial_from_second_name(second_name):
    """Извлекает первую букву отчества и добавляет точку"""
    if not second_name:
        return ""
    
    # Проверяем, что second_name - строка и не пустая
    if isinstance(second_name, str) and len(second_name) > 0:
        first_char = second_name[0].upper()
        if first_char.isalpha():
            return f"{first_char}."
    
    return ""

def process_deal(deal_id):
    """Обрабатывает одну сделку"""
    try:
        deal = bitrix_call("crm.deal.get", {"id": deal_id})
        if not deal:
            logger.debug(f"Сделка {deal_id} не найдена")
            return False
        
        contact_id = deal.get("CONTACT_ID")
        if not contact_id:
            logger.debug(f"В сделке {deal_id} нет контакта")
            return False
        
        contact_info = get_contact_info(contact_id)
        if not contact_info:
            logger.debug(f"Не удалось получить информацию о контакте {contact_id}")
            return False
        
        second_name = contact_info.get("second_name", "")
        initial = get_initial_from_second_name(second_name)
        
        if not initial:
            logger.debug(f"У контакта {contact_id} нет отчества (second_name: '{second_name}')")
            return False
        
        # Проверяем текущее значение поля
        current_initial = deal.get(INITIAL_FIELD)
        
        if current_initial == initial:
            logger.debug(f"Сделка {deal_id} уже имеет инициал '{initial}'")
            return False
        
        # Обновляем поле
        bitrix_call("crm.deal.update", {
            "id": deal_id,
            "fields": {
                INITIAL_FIELD: initial
            }
        })
        
        logger.info(f"✅ Сделка {deal_id}: установлен инициал '{initial}' для контакта {contact_id}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка обработки сделки {deal_id}: {e}")
        return False

def process_stage(stage_id):
    """Обрабатывает все сделки на определённой стадии"""
    try:
        logger.info(f"📋 Обработка стадии: {stage_id}")
        
        deals = bitrix_call_paginated("crm.deal.list", {
            "filter": {
                "STAGE_ID": stage_id
            },
            "select": ["ID", "TITLE", "CONTACT_ID", "STAGE_ID"]
        })
        
        if not deals:
            logger.info(f"   Нет сделок на стадии {stage_id}")
            return 0
        
        logger.info(f"   Найдено сделок: {len(deals)}")
        
        processed = 0
        skipped_no_contact = 0
        skipped_no_second_name = 0
        skipped_already_set = 0
        errors = 0
        
        for deal in deals:
            deal_id = deal.get("ID")
            contact_id = deal.get("CONTACT_ID")
            
            if not contact_id:
                skipped_no_contact += 1
                time.sleep(0.1)
                continue
            
            result = process_deal(deal_id)
            
            if result is True:
                processed += 1
            elif result is False:
                # Проверяем причину
                if not contact_id:
                    skipped_no_contact += 1
                else:
                    # Получаем контакт для диагностики
                    contact_info = get_contact_info(contact_id)
                    if contact_info and contact_info.get("second_name"):
                        skipped_already_set += 1
                    else:
                        skipped_no_second_name += 1
            
            time.sleep(0.2)  # Задержка между запросами
        
        logger.info(f"   📊 Статистика по стадии {stage_id}:")
        logger.info(f"      ✅ Обработано: {processed}")
        logger.info(f"      ⏭️  Нет контакта: {skipped_no_contact}")
        logger.info(f"      ⏭️  Нет отчества: {skipped_no_second_name}")
        logger.info(f"      ⏭️  Уже установлено: {skipped_already_set}")
        logger.info(f"      ❌ Ошибок: {errors}")
        logger.info(f"   ✅ Обработано на стадии {stage_id}: {processed}")
        
        return processed
        
    except Exception as e:
        logger.error(f"Ошибка обработки стадии {stage_id}: {e}")
        return 0

def run():
    """Основная функция для запуска по расписанию"""
    try:
        logger.info("=" * 60)
        logger.info("🚀 ЗАПУСК ОБРАБОТЧИКА ИНИЦИАЛОВ")
        logger.info(f"📊 Стадии для обработки: {', '.join(DEAL_STAGES)}")
        
        total_processed = 0
        for stage_id in DEAL_STAGES:
            processed = process_stage(stage_id)
            total_processed += processed
        
        logger.info(f"📈 ВСЕГО ОБРАБОТАНО: {total_processed} сделок")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")