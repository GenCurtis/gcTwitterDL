# -*- coding: utf-8 -*-
# 封号用户归档:检测到用户被封后,把其下载目录重命名为「【已封号】<用户名>」并清理下载日志
import os
import time
from datetime import datetime

from .logger import logger

# 归档目录名前缀
SUSPENDED_PREFIX = '【已封号】'

# 归档时清理的下载日志文件:csv 记录 + 去重缓存;md 保留(含推文链接,可作内容索引)
CLEAN_FILENAMES = ('cache_data.log',)
CLEAN_EXTS = ('.csv',)


def is_archived(screen_name):
    return screen_name.startswith(SUSPENDED_PREFIX)


def archive_suspended_user(screen_name, save_path):
    """把 downloads/{screen_name} 重命名为「【已封号】screen_name」并清理日志;返回是否执行了归档。
    目录不存在或已归档时返回 False(幂等)。"""
    if is_archived(screen_name):
        return False

    user_dir = os.path.join(save_path, screen_name)
    if not os.path.isdir(user_dir):
        return False

    target = os.path.join(save_path, SUSPENDED_PREFIX + screen_name)
    if os.path.exists(target):
        # 目标已存在(可能是上次归档残留或重名):追加时间戳避免覆盖
        target = os.path.join(save_path, f'{SUSPENDED_PREFIX}{screen_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}')

    _clean_download_logs(user_dir)

    try:
        os.rename(user_dir, target)
    except OSError as e:
        logger.error(f'归档 {screen_name} 失败(重命名): {e}')
        return False
    logger.info(f'用户 {screen_name} 疑似被封号,已归档为 {os.path.basename(target)},并清理下载日志')
    return True


def _clean_download_logs(user_dir):
    for entry in os.listdir(user_dir):
        full = os.path.join(user_dir, entry)
        if os.path.isfile(full):
            if entry in CLEAN_FILENAMES or entry.lower().endswith(CLEAN_EXTS):
                try:
                    os.remove(full)
                except OSError as e:
                    logger.warning(f'清理日志文件失败 {entry}: {e}')
