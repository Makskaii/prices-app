#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# app/handlers/run_initials_daemon.py

import os
import sys
import time
import logging
from datetime import datetime

# Добавляем путь к корню проекта
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from app.handlers.initials_job import run

# Логирование только в stdout (systemd соберёт сам)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("initials_daemon")

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("🚀 ЗАПУСК ДЕМОНА ОБРАБОТКИ ИНИЦИАЛОВ")
    logger.info("=" * 60)
    
    iteration = 0
    while True:
        try:
            iteration += 1
            start_time = datetime.now()
            
            logger.info(f"🔄 Итерация #{iteration} начата в {start_time.strftime('%H:%M:%S')}")
            
            run()
            
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Итерация #{iteration} завершена за {duration:.2f} сек")
            logger.info(f"⏳ Ожидание 15 секунд до следующей итерации...")
            
            time.sleep(15)
            
        except KeyboardInterrupt:
            logger.info("👋 Остановка по запросу пользователя")
            break
        except Exception as e:
            logger.error(f"💥 Критическая ошибка: {e}")
            time.sleep(15)