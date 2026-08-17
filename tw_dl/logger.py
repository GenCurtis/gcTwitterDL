# -*- coding: utf-8 -*-
# 双输出日志:控制台(INFO)+ 滚动文件(DEBUG),沿用 nhentai-dl 的做法
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler


def setup_logger():
    logger = logging.getLogger('gcTwitterDL')
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    # 控制台:INFO 起步,避免刷屏
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    logger.addHandler(console_handler)

    # 文件:DEBUG 全量,滚动 5MB x 5
    logs_dir = Path(__file__).resolve().parent.parent / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(logs_dir / 'gcTwitterDL.log',
                                       maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(file_handler)

    return logger


logger = setup_logger()
