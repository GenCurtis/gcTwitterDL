# -*- coding: utf-8 -*-
# api.get_json 全路径测试:httpx.MockTransport 纯内存模拟,不触网
import httpx
import pytest

from tw_dl.api import TwitterAPI, RateLimitError, AuthError, TwitterAPIError, ResponseStructureError

COOKIE = 'auth_token=x; ct0=y;'


def test_response_structure_error_hierarchy():
    # R6.2:结构异常必须是 TwitterAPIError 子类(_main 的 except 链自动覆盖,调用方语义一致)
    assert issubclass(ResponseStructureError, TwitterAPIError)
    e = ResponseStructureError('boom')
    assert e.status_code is None
    assert isinstance(e, TwitterAPIError)


def make_api(handler):
    return TwitterAPI(COOKIE, transport=httpx.MockTransport(handler))


def no_sleep(monkeypatch):
    monkeypatch.setattr('tw_dl.api.time.sleep', lambda s: None)


def test_get_json_ok(monkeypatch):
    no_sleep(monkeypatch)
    api = make_api(lambda req: httpx.Response(200, json={'a': 1}))
    assert api.get_json('https://x.com/i/api/graphql/abc') == {'a': 1}
    api.close()


def test_get_json_401_auth_error(monkeypatch):
    no_sleep(monkeypatch)
    api = make_api(lambda req: httpx.Response(401, text='unauthorized'))
    with pytest.raises(AuthError):
        api.get_json('http://x/a')
    api.close()


def test_get_json_403_auth_error(monkeypatch):
    no_sleep(monkeypatch)
    api = make_api(lambda req: httpx.Response(403, text='forbidden'))
    with pytest.raises(AuthError):
        api.get_json('http://x/a')
    api.close()


def test_get_json_quota_429_with_phrase_raises_immediately(monkeypatch):
    # 配额耗尽:立即抛,不重试(只调用 1 次)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, text='{"errors":[{"message":"Rate limit exceeded"}]}')

    no_sleep(monkeypatch)
    api = make_api(handler)
    with pytest.raises(RateLimitError):
        api.get_json('http://x/a')
    assert len(calls) == 1
    api.close()


def test_get_json_429_plain_retries_then_quota(monkeypatch):
    # 无配额提示的 429:退避重试,耗尽后仍按配额类处理
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, text='plain')

    no_sleep(monkeypatch)
    api = make_api(handler)
    with pytest.raises(RateLimitError):
        api.get_json('http://x/a', retries=2)
    assert len(calls) == 2
    api.close()


def test_get_json_500_retries_then_twitter_error(monkeypatch):
    # 5xx:重试后抛 TwitterAPIError(不是配额)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500, text='boom')

    no_sleep(monkeypatch)
    api = make_api(handler)
    with pytest.raises(TwitterAPIError) as exc:
        api.get_json('http://x/a', retries=2)
    assert not isinstance(exc.value, RateLimitError)
    assert exc.value.status_code == 500
    assert len(calls) == 2
    api.close()


def test_get_json_network_error_not_rate_limit(monkeypatch):
    # 网络故障重试耗尽 → TwitterAPIError;绝不能误报配额(否则调用方会中止整个批量任务)
    calls = []

    def handler(req):
        calls.append(1)
        raise httpx.ConnectError('dns fail', request=req)

    no_sleep(monkeypatch)
    api = make_api(handler)
    with pytest.raises(TwitterAPIError) as exc:
        api.get_json('http://x/a', retries=2)
    assert not isinstance(exc.value, RateLimitError)
    assert len(calls) == 2
    api.close()


def test_get_json_connect_error_fast_fail(monkeypatch):
    # R8 回归:ConnectError 只重试 1 次即抛(不等满 5 次空等 ~62s)
    calls = []

    def handler(req):
        calls.append(1)
        raise httpx.ConnectError('conn refused', request=req)

    no_sleep(monkeypatch)
    api = make_api(handler)
    with pytest.raises(TwitterAPIError) as exc:
        api.get_json('http://x/a', retries=5)
    assert not isinstance(exc.value, RateLimitError)
    assert len(calls) == 2  # 1 次原始 + 1 次重试,而非 5 次
    api.close()


def test_get_json_rate_limit_text_in_200_body_ignored(monkeypatch):
    # 回归:200 响应体(推文内容)含 'Rate limit exceeded' 字样 → 正常解析,不误判限流
    no_sleep(monkeypatch)
    api = make_api(lambda req: httpx.Response(200, json={'tweet': 'Rate limit exceeded said nobody'}))
    assert api.get_json('http://x/a')['tweet'].startswith('Rate limit')
    api.close()


def test_get_json_invalid_json(monkeypatch):
    no_sleep(monkeypatch)
    api = make_api(lambda req: httpx.Response(200, text='not json at all'))
    with pytest.raises(TwitterAPIError):
        api.get_json('http://x/a')
    api.close()


def test_get_json_404_no_retry(monkeypatch):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(404, text='nope')

    no_sleep(monkeypatch)
    api = make_api(handler)
    with pytest.raises(TwitterAPIError) as exc:
        api.get_json('http://x/a')
    assert exc.value.status_code == 404
    assert len(calls) == 1
    api.close()


def test_get_json_success_after_retry(monkeypatch):
    # 先 500 后 200 → 重试后成功
    state = {'n': 0}

    def handler(req):
        state['n'] += 1
        if state['n'] == 1:
            return httpx.Response(500, text='boom')
        return httpx.Response(200, json={'ok': True})

    no_sleep(monkeypatch)
    api = make_api(handler)
    assert api.get_json('http://x/a', retries=3) == {'ok': True}
    assert state['n'] == 2
    api.close()


def test_async_client_lazy_and_lifecycle(monkeypatch):
    # AsyncClient 惰性创建:ensure 之前为 None,aclose 后复位;同一实例复用
    no_sleep(monkeypatch)
    api = TwitterAPI(COOKIE, transport=httpx.MockTransport(lambda req: httpx.Response(200, json={})))
    assert api.async_client is None
    c1 = api.ensure_async_client()
    assert api.async_client is c1
    c2 = api.ensure_async_client()
    assert c1 is c2
    import asyncio
    asyncio.run(api.aclose())
    assert api.async_client is None
    api.close()
