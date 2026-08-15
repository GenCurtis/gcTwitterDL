# -*- coding: utf-8 -*-
# tag_down 搜索页终止判定(R6:空页不再立即停,连续多页空才停)
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))

from tag_down import _is_search_done  # noqa: E402


def test_none_stops_immediately():
    # 出错/无更多结果(真尽头)→ 立即停,不计入空页
    stop, n = _is_search_done(None, 0)
    assert stop is True and n == 0
    stop, n = _is_search_done(None, 1)
    assert stop is True


def test_single_empty_page_does_not_stop():
    # R6 核心:单页空(一页全是纯文本/解析失败)→ 继续翻页,不误停
    stop, n = _is_search_done([], 0)
    assert stop is False and n == 1
    stop, n = _is_search_done([], 1)
    assert stop is True and n == 2  # 连续 2 页空才停


def test_normal_page_resets_counter():
    stop, n = _is_search_done(['media1'], 2)
    assert stop is False and n == 0
