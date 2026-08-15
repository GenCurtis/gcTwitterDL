# -*- coding: utf-8 -*-
# 已下载 URL 记录(替代原 cache_gen.py):每次新增即原子落盘,崩溃/中断不再丢缓存
import os
import pickle

from .logger import logger


class DownloadCache:
    def __init__(self, save_path):
        self.cache_path = os.path.join(save_path, 'cache_data.log')
        self.data = set()
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, 'rb') as f:
                    self.data = pickle.load(f)
            except Exception as e:
                logger.warning(f'cache_data.log 读取失败({e}),已重建缓存')

    def is_downloaded(self, url):
        """该 URL 是否已成功下载过(仅由 mark 登记,失败的文件不在其中,下次可重试)"""
        return url in self.data

    def mark(self, url):
        """下载成功后登记并立即原子落盘。失败的文件不要 mark——否则永久漏下载(曾因提前入库丢文件)"""
        self.data.add(url)
        self.persist()

    def persist(self):
        # 先写临时文件再原子替换,避免写一半损坏
        tmp_path = self.cache_path + '.tmp'
        with open(tmp_path, 'wb') as f:
            pickle.dump(self.data, f)
        os.replace(tmp_path, self.cache_path)
