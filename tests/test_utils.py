# -*- coding: utf-8 -*-
import pytest

from tw_dl.utils import (
    quote_url, del_special_char, stamp2time, time2stamp, time_comparison,
    get_tweet_msecs, get_highest_video_quality, hash_save_token, build_headers,
    extract_latest_media_id, check_user_status,
)


def test_quote_url_escapes_braces():
    assert quote_url('a{b}c') == 'a%7Bb%7Dc'
    assert quote_url('plain') == 'plain'


def test_del_special_char():
    assert del_special_char('#ヨルクラ') == '#ヨルクラ'
    assert del_special_char('a/b\\c: d') == 'abcd'  # 空格同样会被过滤(与原实现一致)
    assert del_special_char('test.txt') == 'test.txt'
    assert del_special_char('img.jpeg') == 'img.jpeg'
    assert del_special_char('ab', keep='') == 'ab'
    assert del_special_char('a[b', keep='[') == 'a[b'  # keep 含正则特殊字符时按字面保留
    assert del_special_char('') == ''


def test_stamp_roundtrip():
    ts = time2stamp('2024-04-21')
    # 同一天内,还原字符串应一致(本地时区)
    assert stamp2time(ts)[:10] == '2024-04-21'


def test_time_comparison():
    start, end = 1000, 2000
    down, label = time_comparison(1500, start, end)   # 区间内
    assert down is True and label is True
    down, label = time_comparison(500, start, end)    # 早于区间:停止
    assert down is False and label is False
    down, label = time_comparison(3000, start, end)   # 晚于区间:跳过但继续
    assert down is False and label is True


def test_time_comparison_boundaries():
    # 恰好等于 start/end 必须判定为命中(边界闭合)
    start, end = 1000, 2000
    assert time_comparison(1000, start, end) == [True, True]
    assert time_comparison(2000, start, end) == [True, True]
    # 恰好差 1 毫秒即不命中
    assert time_comparison(999, start, end) == [False, False]
    assert time_comparison(2001, start, end) == [False, True]


def test_get_tweet_msecs_new_edit_control():
    result = {'edit_control': {'editable_until_msecs': '3600000'}}
    assert get_tweet_msecs(result) is None  # 1h - 1h = 0,视为无效

    result = {'edit_control': {'editable_until_msecs': '3601000000'}}
    assert get_tweet_msecs(result) == 3597400000


def test_get_tweet_msecs_old_edit_control():
    result = {'edit_control': {'edit_control_initial': {'editable_until_msecs': '3601000000'}}}
    assert get_tweet_msecs(result) == 3597400000


def test_get_tweet_msecs_invalid():
    assert get_tweet_msecs({}) is None
    assert get_tweet_msecs({'edit_control': {}}) is None


def test_get_tweet_msecs_prefers_created_at():
    # R1:created_at(精确,UTC 秒级)优先于 edit_control 近似(±30min)
    result = {
        'legacy': {'created_at': 'Tue Apr 21 07:30:00 +0000 2024'},
        'edit_control': {'editable_until_msecs': '1713690000000'},  # 09:00 UTC - 1h = 08:30(近似值)
    }
    assert get_tweet_msecs(result) == 1713684600000  # 精确的 07:30 UTC


def test_get_tweet_msecs_falls_back_without_created_at():
    result = {'edit_control': {'editable_until_msecs': '1713690000000'}}
    assert get_tweet_msecs(result) == 1713686400000  # 08:30(近似)


def test_get_tweet_msecs_bad_created_at_falls_back():
    # created_at 格式变动 → 静默回退近似,不崩溃
    result = {'legacy': {'created_at': 'bogus format'},
              'edit_control': {'editable_until_msecs': '1713690000000'}}
    assert get_tweet_msecs(result) == 1713686400000


def test_check_user_status():
    assert check_user_status(None) == 'not_found'
    assert check_user_status({'__typename': 'UserUnavailable'}) == 'suspended'
    assert check_user_status({'__typename': 'UserTombstone'}) == 'suspended'
    assert check_user_status({'__typename': 'UserUnavailableTombstone'}) == 'suspended'
    assert check_user_status({'__typename': 'User'}) == 'ok'
    assert check_user_status({}) == 'ok'  # 无 __typename → 保守按正常处理


def test_get_highest_video_quality():
    variants = [{'bitrate': 100, 'url': 'a'}, {'bitrate': 900, 'url': 'b'}, {'bitrate': 500, 'url': 'c'}]
    assert get_highest_video_quality(variants) == 'b'
    # 单 variant(gif)
    assert get_highest_video_quality([{'url': 'gif'}]) == 'gif'


def test_hash_save_token():
    assert len(hash_save_token('https://example.com/a.jpg')) == 8  # 4 位 → 8 位,降低碰撞
    assert hash_save_token('abc') == hash_save_token('abc')


def test_build_headers():
    headers = build_headers('auth_token=xxx; ct0=yyy;')
    assert headers['x-csrf-token'] == 'yyy'
    assert headers['cookie'] == 'auth_token=xxx; ct0=yyy;'
    assert 'authorization' in headers


def test_build_headers_empty_cookie():
    with pytest.raises(ValueError):
        build_headers('')


def _media_entry(entry_id, tweet_id):
    # 构造 UserMedia 第一页 timeline-module 条目(与 main.py First_Page 处理的结构一致)
    return {
        'entryId': entry_id,
        'content': {
            'items': [{
                'item': {
                    'itemContent': {
                        'tweet_results': {'result': {'rest_id': tweet_id, 'edit_control': {'editable_until_msecs': 'x'}}},
                    },
                },
            }],
        },
    }


def _media_raw(entries):
    return {'data': {'user': {'result': {'timeline_v2': {'timeline': {'instructions': [{'entries': entries}]}}}}}}


def test_extract_latest_media_id_normal():
    raw = _media_raw([_media_entry('timeline-module-1', '1800000000000000000')])
    assert extract_latest_media_id(raw) == 1800000000000000000


def test_extract_latest_media_id_skips_promoted_cursor_pin():
    raw = _media_raw([
        _media_entry('promoted-tweet-1', '100'),
        _media_entry('cursor-bottom', '200'),
        _media_entry('timeline-module-pin-1', '300'),
        _media_entry('timeline-module-1', '400'),
    ])
    assert extract_latest_media_id(raw) == 400


def test_extract_latest_media_id_limited_account_unwrap():
    # 限制回复账号:result 内层包 'tweet'
    entry = {
        'entryId': 'timeline-module-1',
        'content': {'items': [{
            'item': {'itemContent': {'tweet_results': {
                'result': {'tweet': {'rest_id': '999', 'edit_control': {'editable_until_msecs': 'x'}}},
            }}},
        }]},
    }
    assert extract_latest_media_id(_media_raw([entry])) == 999


def test_extract_latest_media_id_empty_and_broken():
    assert extract_latest_media_id(_media_raw([])) is None
    assert extract_latest_media_id({'data': {'user': {'result': None}}}) is None
    assert extract_latest_media_id({'unexpected': 'structure'}) is None
    # 有条目但都解析失败
    raw = _media_raw([{'entryId': 'timeline-module-1', 'content': {'items': [{'item': {}}]}}])
    assert extract_latest_media_id(raw) is None
