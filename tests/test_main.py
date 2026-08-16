# -*- coding: utf-8 -*-
# main() 全流程测试(API 全 mock):多用户状态复位回归、封号归档、注销、配额中断
import glob
import os
import shutil

import pytest

import main as M
from tw_dl.api import RateLimitError
from tw_dl.user_info import User_info

TS = 1700000000000  # 2023-11-15,默认时间范围(1990~2050)内
PAGE_Q = []


def _tweet_item(tid):
    return {'entryId': f'tweet-{tid}',
            'item': {'itemContent': {'tweet_results': {'result': {
                'rest_id': str(tid),
                'edit_control': {'editable_until_msecs': str(TS + 3600000)},
                'legacy': {'favorite_count': 1, 'retweet_count': 2, 'reply_count': 3,
                           'full_text': f'text {tid}',
                           'extended_entities': {'media': [{'media_url_https': f'https://pbs.twimg.com/media/{tid}.jpg',
                                                             'expanded_url': f'https://x.com/u/status/{tid}'}]}}}}}}}


def _page1(tid):
    return {'data': {'user': {'result': {'timeline_v2': {'timeline': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': [
            {'entryId': 'timeline-module-1', 'content': {'items': [_tweet_item(tid)]}},
            {'entryId': 'cursor-bottom-1', 'content': {'value': 'c1'}},
        ]},
    ]}}}}}}


def _pageN(tid):
    return {'data': {'user': {'result': {'timeline_v2': {'timeline': {'instructions': [
        {'type': 'TimelineAddToModule', 'moduleItems': [_tweet_item(tid)]},
        {'type': 'TimelineAddEntries', 'entries': [{'entryId': 'cursor-bottom-2', 'content': {'value': 'c2'}}]},
    ]}}}}}}


def _page_end():
    return {'data': {'user': {'result': {'timeline_v2': {'timeline': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': []},
    ]}}}}}}


def _stuck_page(tid):
    # 与 _pageN 同构,但 cursor 值不变(c1)→ 停滞
    return {'data': {'user': {'result': {'timeline_v2': {'timeline': {'instructions': [
        {'type': 'TimelineAddToModule', 'moduleItems': [_tweet_item(tid)]},
        {'type': 'TimelineAddEntries', 'entries': [{'entryId': 'cursor-bottom-1', 'content': {'value': 'c1'}}]},
    ]}}}}}}


def _info(typename='User'):
    return {'data': {'user': {'result': {'__typename': typename, 'rest_id': '123',
                                         'legacy': {'name': 'N', 'statuses_count': 10, 'media_count': 5}}}}}


def _user_pages(tag):
    return [_info(), _page1(f'{tag}a'), _pageN(f'{tag}b'), _page_end()]


class FakeResp:
    def __init__(self, status_code=200, content=b'img'):
        self.status_code = status_code
        self.content = content


class FakeAC:
    async def get(self, url):
        return FakeResp()


class FakeAPI:
    """模拟 TwitterAPI:get_json 按序弹页;媒体下载成功"""
    def __init__(self, cookie, proxy=None):
        self.client = object()
        self.async_client = None

    def get_json(self, url):
        return PAGE_Q.pop(0)

    def ensure_async_client(self):
        self.async_client = FakeAC()
        return self.async_client

    async def aclose(self):
        self.async_client = None

    def close(self):
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(M, 'TwitterAPI', FakeAPI)
    monkeypatch.setattr(M.config, 'save_path', str(tmp_path))
    monkeypatch.setattr(M.config, 'cookie', 'auth_token=x; ct0=y;')
    monkeypatch.setattr(M.config, 'has_retweet', False)
    monkeypatch.setattr(M.config, 'has_highlights', False)
    monkeypatch.setattr(M.config, 'has_likes', False)
    monkeypatch.setattr(M.config, 'autoSync', False)
    monkeypatch.setattr(M.config, 'down_log', False)
    monkeypatch.setattr(M.config, 'md_output', False)
    monkeypatch.setattr(M.config, 'log_output', False)
    monkeypatch.setattr(M.config, 'has_video', False)
    monkeypatch.setattr(M.config, 'orig_format', True)
    monkeypatch.setattr(M.config, 'img_format', 'jpg')
    monkeypatch.setattr(M.config, 'max_concurrent_requests', 8)
    monkeypatch.setattr(M.config, 'content_dedup', False)  # mock 内容相同,关闭去重(去重行为由 test_dedup 专项覆盖)
    monkeypatch.setattr(M.config, 'time_range', '')
    monkeypatch.setattr(M.config, 'start_stamp', 655028357000)
    monkeypatch.setattr(M.config, 'end_stamp', 2548484357000)
    PAGE_Q.clear()
    return tmp_path


def _media_files(d):
    # 文件名模式:{时间戳}-{推文ID}-img{idx}.ext(方案 A,无 count 下划线)
    return [f for f in os.listdir(d) if '-img' in f or '-vid' in f]


def test_multi_user_state_reset_regression(env):
    # 回归:连续两个用户,第二个必须完整下载(曾因 start_label/First_Page 全局未复位而静默零下载)
    PAGE_Q.extend(_user_pages('u1'))
    PAGE_Q.extend(_user_pages('u2'))

    assert M.main(User_info('u1')) is True
    assert M.main(User_info('u2')) is True

    assert len(_media_files(str(env / 'u1'))) == 2
    assert len(_media_files(str(env / 'u2'))) == 2


def test_main_uses_time_range_to_stop(env, monkeypatch):
    # 推文早于时间范围 → start_label 置 False,停止拉取但正常返回 True
    PAGE_Q.extend(_user_pages('u1'))
    monkeypatch.setattr(M.config, 'start_stamp', 1750000000000)  # 2025-06 之后
    monkeypatch.setattr(M.config, 'end_stamp', 2548484357000)
    assert M.main(User_info('u1')) is True
    assert _media_files(str(env / 'u1')) == []


def test_suspended_user_archived(env):
    PAGE_Q.append(_info('UserUnavailable'))
    user_dir = env / 'u1'
    user_dir.mkdir()
    (user_dir / '1.jpg').write_bytes(b'x')

    assert M.main(User_info('u1')) is False
    assert not user_dir.exists()
    assert (env / '【已封号】u1').is_dir()


def test_not_found_user(env):
    PAGE_Q.append({'data': {'user': {'result': None}}})
    assert M.main(User_info('ghost')) is False


def test_cursor_stall_detected(env, monkeypatch):
    # R2 回归:后续页 cursor 不再推进(响应结构变动)→ 提前结束而非无限重复拉取。
    # 无防护时 get_download_url 会无限消费同一页(死循环/烧配额)
    class StuckCursorAPI(FakeAPI):
        calls = 0

        def get_json(self, url):
            StuckCursorAPI.calls += 1
            if 'UserByScreenName' in url:
                return _info()
            if StuckCursorAPI.calls == 2:
                return _page1('s1')     # 首页:cursor → c1
            return _stuck_page('s1')    # 之后永远返回同一 cursor 的页(停滞)

    monkeypatch.setattr(M, 'TwitterAPI', StuckCursorAPI)
    assert M.main(User_info('u1')) is True
    # 首页媒体已下载;停滞页内容被丢弃但未重复请求
    assert len(_media_files(str(env / 'u1'))) == 1
    assert StuckCursorAPI.calls == 3   # info + 首页 + 停滞页(一次)即停


def test_structural_error_returns_false(env, monkeypatch):
    # R6.2 回归:响应结构损坏 → main() 返回 False(而非「完整完成」)
    class BrokenAPI(FakeAPI):
        def get_json(self, url):
            if 'UserByScreenName' in url:
                return _info()
            return {'data': {'user': {'result': {'timeline_v2': {'timeline': {'instructions': []}}}}}}

    monkeypatch.setattr(M, 'TwitterAPI', BrokenAPI)
    ui = User_info('u1')
    assert M.main(ui) is False
    assert ui.last_error == 'structure'  # C1:个体性问题,后续用户可继续
    assert _media_files(str(env / 'u1')) == []


def test_quota_sets_last_error(env, monkeypatch):
    # 配额 → last_error='rate_limit'(sync_down 据此 break)
    class QuotaAPI(FakeAPI):
        def get_json(self, url):
            raise RateLimitError('quota')

    monkeypatch.setattr(M, 'TwitterAPI', QuotaAPI)
    ui = User_info('u1')
    assert M.main(ui) is False
    assert ui.last_error == 'rate_limit'


def test_quota_aborts(env, monkeypatch):
    class QuotaAPI(FakeAPI):
        def get_json(self, url):
            raise RateLimitError('quota')

    monkeypatch.setattr(M, 'TwitterAPI', QuotaAPI)
    assert M.main(User_info('u1')) is False


def test_main_logs_key_events(env, monkeypatch, caplog):
    # B1:关键事件写日志(可观测性;print 保留给控制台)
    import logging
    caplog.set_level(logging.INFO, logger='twitter_download')
    PAGE_Q.extend(_user_pages('u1'))
    assert M.main(User_info('u1')) is True
    messages = [r.message for r in caplog.records]
    assert any('开始拉取 u1' in m for m in messages)
    assert any('u1 拉取结束' in m for m in messages)


def test_partial_download_then_structural_error(env, monkeypatch):
    # 第一页成功、第二页结构损坏:已下载文件保留,main 返回 False
    class PartialAPI(FakeAPI):
        def get_json(self, url):
            if 'UserByScreenName' in url:
                return _info()
            if not hasattr(self, '_p1'):
                self._p1 = True
                return _page1('p1')
            return {'data': {'user': {'result': {'timeline_v2': {'timeline': {'instructions': []}}}}}}

    monkeypatch.setattr(M, 'TwitterAPI', PartialAPI)
    assert M.main(User_info('u1')) is False
    assert len(_media_files(str(env / 'u1'))) == 1  # 第一页媒体保留


def test_entry_parse_failure_logged(env, monkeypatch, caplog):
    # R3:条目级解析失败留 debug 日志(不再完全静默),且不中断整页、不影响其他条目
    import logging
    caplog.set_level(logging.DEBUG, logger='twitter_download')

    def bad_page():
        return {'data': {'user': {'result': {'timeline_v2': {'timeline': {'instructions': [
            {'type': 'TimelineAddEntries', 'entries': [
                {'entryId': 'timeline-module-1', 'content': {'items': [
                    {'entryId': 'tweet-bad', 'item': {'itemContent': {'tweet_results': {'result': {'legacy': {}}}}}},  # 缺字段 → 条目级失败
                    _tweet_item('ok1'),
                ]}},
                {'entryId': 'cursor-bottom-1', 'content': {'value': 'c1'}},
            ]},
        ]}}}}}}

    class BadEntryAPI(FakeAPI):
        def get_json(self, url):
            if 'UserByScreenName' in url:
                return _info()
            return bad_page()

    monkeypatch.setattr(M, 'TwitterAPI', BadEntryAPI)
    assert M.main(User_info('u1')) is True
    assert len(_media_files(str(env / 'u1'))) == 1  # 好条目正常下载
    assert any('条目解析失败' in r.message for r in caplog.records)


def test_rest_id_cache_skips_screen_name_call(env, monkeypatch):
    # 配额压缩:sync_down 状态缓存命中 → 免调 UserByScreenName(全量拉取省 ~26% 配额)
    import csv as csvmod
    import json
    (env / '_sync_state.json').write_text(json.dumps(
        {'u1': {'rest_id': '123', 'latest_media_id': 500, 'checked_at': 'x', 'name': '缓存昵称'}}
    ), encoding='utf-8')

    class CacheAPI(FakeAPI):
        usn_calls = 0

        def get_json(self, url):
            if 'UserByScreenName' in url:
                CacheAPI.usn_calls += 1
                return _info()
            if not hasattr(self, '_p1'):
                self._p1 = True
                return _page1('c1')
            return _page_end()

    monkeypatch.setattr(M, 'TwitterAPI', CacheAPI)
    assert M.main(User_info('u1')) is True
    assert CacheAPI.usn_calls == 0
    assert len(_media_files(str(env / 'u1'))) == 1
    csv_path = glob.glob(str(env / 'u1' / '*.csv'))[0]
    with open(csv_path, encoding='utf-8-sig') as f:
        rows = list(csvmod.reader(f))
    assert rows[0] == ['缓存昵称', 'u1']  # 头部使用缓存昵称


def test_no_cache_still_calls_screen_name(env, monkeypatch):
    # 无缓存 → 照常调用 UserByScreenName(回退路径)
    class NCacheAPI(FakeAPI):
        usn_calls = 0

        def get_json(self, url):
            if 'UserByScreenName' in url:
                NCacheAPI.usn_calls += 1
                return _info()
            if not hasattr(self, '_p1'):
                self._p1 = True
                return _page1('c1')
            return _page_end()

    monkeypatch.setattr(M, 'TwitterAPI', NCacheAPI)
    assert M.main(User_info('u1')) is True
    assert NCacheAPI.usn_calls == 1


def test_corrupt_cache_falls_back(env, monkeypatch):
    # 缓存文件损坏 → 回退 UserByScreenName,不崩溃
    (env / '_sync_state.json').write_text('{not json', encoding='utf-8')

    class CorruptAPI(FakeAPI):
        usn_calls = 0

        def get_json(self, url):
            if 'UserByScreenName' in url:
                CorruptAPI.usn_calls += 1
                return _info()
            if not hasattr(self, '_p1'):
                self._p1 = True
                return _page1('c1')
            return _page_end()

    monkeypatch.setattr(M, 'TwitterAPI', CorruptAPI)
    assert M.main(User_info('u1')) is True
    assert CorruptAPI.usn_calls == 1


def test_autosync_start_stamp_new_filename_format(tmp_path):
    # R10 回归:新文件名(-vid0/-img0)下 autoSync 起点 = 最新媒体文件日期,而非 1990 兜底全量重拉
    (tmp_path / '2026-08-14 15-28-2088165769360376106-vid0.mp4').write_bytes(b'x')
    (tmp_path / '2026-08-16 17-50-2088926441757118802-vid0.mp4').write_bytes(b'y')
    (tmp_path / '2026-08-16 21-00-07.csv').write_text('a')
    assert M._autosync_start_stamp(str(tmp_path), M.backup_stamp) == M.time2stamp('2026-08-16')


def test_autosync_start_stamp_old_format_compat(tmp_path):
    # 旧上游格式(-img_0.jpg)仍兼容
    (tmp_path / '2026-08-14 15-28-2088165769360376106-img_0.jpg').write_bytes(b'x')
    assert M._autosync_start_stamp(str(tmp_path), M.backup_stamp) == M.time2stamp('2026-08-14')


def test_autosync_start_stamp_fallback_without_media(tmp_path):
    # 目录为空/无媒体文件 → 兜底(全量语义不变)
    (tmp_path / 'u1-2026-08-16_21-00-07.csv').write_text('a')
    assert M._autosync_start_stamp(str(tmp_path), M.backup_stamp) == M.backup_stamp
    assert M._autosync_start_stamp(str(tmp_path / 'missing'), M.backup_stamp) == M.backup_stamp


def _tweet_ts(tid, msecs):
    item = _tweet_item(tid)
    item['item']['itemContent']['tweet_results']['result']['edit_control']['editable_until_msecs'] = str(msecs + 3600000)
    return item


def _page_ts(tid, msecs, cursor):
    return {'data': {'user': {'result': {'timeline_v2': {'timeline': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': [
            {'entryId': f'tweet-{tid}', 'content': {'items': [_tweet_ts(tid, msecs)]}},
            {'entryId': 'cursor-bottom-1', 'content': {'value': cursor}},
        ]},
    ]}}}}}}

def _pageN_ts(tid, msecs):
    return {'data': {'user': {'result': {'timeline_v2': {'timeline': {'instructions': [
        {'type': 'TimelineAddToModule', 'moduleItems': [_tweet_ts(tid, msecs)]},
        {'type': 'TimelineAddEntries', 'entries': [{'entryId': 'cursor-bottom-2', 'content': {'value': 'c2'}}]},
    ]}}}}}}


def test_incremental_sync_only_downloads_new_media(env, monkeypatch):
    # R11 端到端增量语义:磁盘已有媒体 → autoSync 起点 = 最新文件日期 →
    # 只拉新推文、旧推文不重下、旧文件不被重写。
    # 曾因文件名格式失配(-vid_ vs -vid0)起点退化为 1990 → 每次增量全量重拉(952 文件/次)
    disk_ts = M.time2stamp('2026-08-12') + 9 * 3600000       # 磁盘已有:08-12 09:00 → 起点=08-12
    new_ts = M.time2stamp('2026-08-16') + 17 * 3600000 + 50 * 60000  # 新推文:08-16 17:50
    old_ts = M.time2stamp('2026-08-10') + 10 * 3600000       # 旧推文:08-10(早于起点,不得重拉)
    old_file = f'{M.stamp2time(disk_ts)}-100-img0.jpg'
    (env / 'u1').mkdir()
    (env / 'u1' / old_file).write_bytes(b'old-content')
    PAGE_Q.extend([_info(), _page_ts(200, new_ts, 'c1'), _pageN_ts(99, old_ts), _page_end()])
    monkeypatch.setattr(M.config, 'autoSync', True)
    monkeypatch.setattr(M.config, 'start_stamp', M.backup_stamp)  # 匹配失效时兜底=1990 → 全量重拉
    assert M.main(User_info('u1')) is True
    media = [f for f in os.listdir(env / 'u1') if '-img' in f or '-vid' in f]
    assert sorted(media) == sorted([old_file, f'{M.stamp2time(new_ts)}-200-img0.jpg'])
    assert (env / 'u1' / old_file).read_bytes() == b'old-content'  # 未被覆盖
