# -*- coding: utf-8 -*-
import csv

from tw_dl.csv_writer import CsvWriter
from tw_dl.utils import time2stamp


def _read_all(path):
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        return list(csv.reader(f))


def test_headers_and_stamp_conversion(tmp_path):
    p = tmp_path / 'out.csv'
    w = CsvWriter(str(tmp_path), 'out.csv',
                  [['user', 'screen'], ['Tweet Range : x']],
                  ['Date', 'Name'], stamp_index=0)
    ts = time2stamp('2024-04-21')
    w.write([ts, 'bob'])
    w.close()

    rows = _read_all(p)
    assert rows[0] == ['user', 'screen']
    assert rows[1] == ['Tweet Range : x']
    assert rows[2] == ['Date', 'Name']
    assert rows[3][0].startswith('2024-04-21')  # 时间戳已转字符串
    assert rows[3][1] == 'bob'


def test_no_stamp_index_passthrough(tmp_path):
    p = tmp_path / 'out.csv'
    w = CsvWriter(str(tmp_path), 'out.csv', [], ['A'], stamp_index=None)
    w.write(['raw'])
    w.close()
    assert _read_all(p) == [['A'], ['raw']]
