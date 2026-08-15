# -*- coding: utf-8 -*-
# 统一 CSV 写出(合并原 main/tag/reply/text 四个几乎相同的 csv_gen)
import os
import csv

from .utils import stamp2time


class CsvWriter:
    def __init__(self, save_path, filename, pre_rows, columns, stamp_index=None):
        """pre_rows: 表头前的信息行(如用户/时间范围);stamp_index: 时间戳列下标(写前自动转字符串)"""
        self.f = open(os.path.join(save_path, filename), 'w', encoding='utf-8-sig', newline='')
        self.writer = csv.writer(self.f)
        for row in pre_rows:
            self.writer.writerow(row)
        self.writer.writerow(columns)
        self.stamp_index = stamp_index

    def write(self, row):
        if self.stamp_index is not None:
            row[self.stamp_index] = stamp2time(row[self.stamp_index])
        self.writer.writerow(row)

    def close(self):
        self.f.close()
