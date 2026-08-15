# -*- coding: utf-8 -*-
import asyncio
import os

import httpx
import pytest

from tw_dl.downloader import get_fallback_url, fetch_media, download_many, MediaFetchError


class FakeResp:
    def __init__(self, status_code, content=b'ok'):
        self.status_code = status_code
        self.content = content


class FakeClient:
    """按调用顺序返回 responses,最后一个一直重复;可注入网络错误"""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url):
        self.calls.append(url)
        if len(self.responses) == 1:
            resp = self.responses[0]
        else:
            resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def _run(coro):
    return asyncio.run(coro)


def test_get_fallback_url():
    assert get_fallback_url('https://x/img.jpg?name=orig') == 'https://x/img.jpg?name=4096x4096'
    assert get_fallback_url('https://x/img.jpg?format=jpg&name=4096x4096') is None
    assert get_fallback_url('https://x/v.mp4') is None


def test_fetch_media_success():
    client = FakeClient([FakeResp(200)])
    assert _run(fetch_media(client, 'http://x/a.jpg')) == b'ok'


def test_fetch_media_404_with_fallback():
    # orig 404 → 降级 4096x4096 → 成功
    client = FakeClient([FakeResp(404), FakeResp(200, b'fallback')])
    content = _run(fetch_media(client, 'http://x/a.jpg?name=orig'))
    assert content == b'fallback'
    assert 'name=4096x4096' in client.calls[1]


def test_fetch_media_404_without_fallback_gives_up():
    # 无降级可用的 404 必须立即放弃,不能无限重试
    client = FakeClient([FakeResp(404)])
    with pytest.raises(MediaFetchError):
        _run(fetch_media(client, 'http://x/a.jpg?name=4096x4096', fallback=True))
    assert len(client.calls) == 1


def test_fetch_media_403_gives_up_immediately():
    # A2 回归:403(地区/版权限制)永久失败,立即放弃不重试
    client = FakeClient([FakeResp(403)])
    with pytest.raises(MediaFetchError) as exc:
        _run(fetch_media(client, 'http://x/a.jpg', max_retries=50))
    assert '403' in str(exc.value)
    assert len(client.calls) == 1


def test_fetch_media_410_gives_up_immediately():
    # 410(资源已删除)同 403,立即放弃
    client = FakeClient([FakeResp(410)])
    with pytest.raises(MediaFetchError):
        _run(fetch_media(client, 'http://x/a.jpg', max_retries=50))
    assert len(client.calls) == 1


def test_fetch_media_404_fallback_also_404_gives_up():
    client = FakeClient([FakeResp(404), FakeResp(404)])
    with pytest.raises(MediaFetchError):
        _run(fetch_media(client, 'http://x/a.jpg?name=orig'))
    assert len(client.calls) == 2


def test_fetch_media_network_error_retries_then_fails():
    client = FakeClient([httpx.ConnectError('boom', request=httpx.Request('GET', 'http://x/a.jpg'))])
    with pytest.raises(MediaFetchError):
        _run(fetch_media(client, 'http://x/a.jpg', max_retries=3))
    assert len(client.calls) == 3


def test_download_many_saves_and_hooks(tmp_path):
    client = FakeClient([FakeResp(200, b'data1'), FakeResp(200, b'data2')])
    api = type('API', (), {'async_client': client})()
    f1, f2 = tmp_path / '1.jpg', tmp_path / '2.jpg'
    calls = []
    jobs = [('http://x/1.jpg', str(f1), False, 'a'), ('http://x/2.jpg', str(f2), False, 'b')]
    failed = _run(download_many(api, jobs, pre_hook=lambda u, f, e: calls.append(('pre', e)),
                                post_hook=lambda u, f, e: calls.append(('post', e))))
    assert failed == []
    assert f1.read_bytes() == b'data1'
    assert f2.read_bytes() == b'data2'
    # pre 顺序固定(任务创建顺序),post 顺序不保证(并发完成)
    assert [c for c in calls if c[0] == 'pre'] == [('pre', 'a'), ('pre', 'b')]
    assert {c for c in calls if c[0] == 'post'} == {('post', 'a'), ('post', 'b')}


def test_download_many_failure_isolated(tmp_path):
    client = FakeClient([FakeResp(404), FakeResp(200, b'data2')])
    api = type('API', (), {'async_client': client})()
    f1, f2 = tmp_path / '1.jpg', tmp_path / '2.jpg'
    jobs = [('http://x/1.jpg?name=4096x4096', str(f1), True, None), ('http://x/2.jpg', str(f2), False, None)]
    failed = _run(download_many(api, jobs))
    assert len(failed) == 1 and '404' in str(failed[0][2])
    assert not f1.exists()
    assert f2.read_bytes() == b'data2'


class _FakeDedup:
    """可控去重器:记录 decide 调用,按脚本返回"""
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def decide(self, md5, filename):
        self.calls.append((md5, os.path.basename(filename)))
        return self.results.pop(0)


def test_atomic_write_no_tmp_left(tmp_path):
    # 原子写:落盘成功且无 .tmp 残留
    client = FakeClient([FakeResp(200, b'data')])
    api = type('API', (), {'async_client': client})()
    f = tmp_path / 'a.jpg'
    _run(download_many(api, [('http://x/a.jpg', str(f), False, None)]))
    assert f.read_bytes() == b'data'
    assert not (tmp_path / 'a.jpg.tmp').exists()


def test_dedup_drop_skips_file_but_runs_post_hook(tmp_path):
    # 去重命中:文件不落盘,但 post_hook 照常调用(CSV 记录推文事实)
    import hashlib
    client = FakeClient([FakeResp(200, b'dup')])
    api = type('API', (), {'async_client': client})()
    f = tmp_path / 'a.jpg'
    hooks = []
    dedup = _FakeDedup(['drop'])
    _run(download_many(api, [('http://x/a.jpg', str(f), False, 'extra')],
                       post_hook=lambda u, fn, e: hooks.append(('post', e)), dedup=dedup))
    assert not f.exists()          # 未落盘
    assert hooks == [('post', 'extra')]  # CSV 照写
    assert dedup.calls[0][0] == hashlib.md5(b'dup').hexdigest()  # md5 已计算


def test_dedup_keep_writes_file(tmp_path):
    client = FakeClient([FakeResp(200, b'new')])
    api = type('API', (), {'async_client': client})()
    f = tmp_path / 'a.jpg'
    dedup = _FakeDedup(['keep'])
    _run(download_many(api, [('http://x/a.jpg', str(f), False, None)], dedup=dedup))
    assert f.read_bytes() == b'new'
