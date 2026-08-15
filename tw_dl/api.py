# -*- coding: utf-8 -*-
# X 非官方 API 客户端:共享连接、退避重试、类型化异常(借鉴 nhentai-dl 的 api.py)
import time

import httpx

from .utils import UA, quote_url, build_headers
from .logger import logger


class TwitterAPIError(Exception):
    def __init__(self, message, status_code=None, response_text=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class RateLimitError(TwitterAPIError):
    """API 当日配额耗尽(429 / 响应含 'Rate limit exceeded')"""


class AuthError(TwitterAPIError):
    """cookie 失效或缺少 ct0(401/403)"""


class ResponseStructureError(TwitterAPIError):
    """API 响应结构与预期不符(非官方 API 结构变动):调用方不应把本次拉取记为完成,
    应中断并允许下次重试——宁可重试耗配额,不可静默丢内容"""


class TwitterAPI:
    def __init__(self, cookie, proxy=None, transport=None):
        """transport 仅供测试注入(httpx.MockTransport);async_client 惰性创建——
        必须在事件循环内创建/关闭(循环外创建会泄漏且关闭时报错),由 download_control 的
        asyncio.run 内 ensure_async_client() + aclose() 管理生命周期。"""
        self.headers = build_headers(cookie)
        self.proxies = proxy
        self._transport = transport
        self.client = httpx.Client(headers=self.headers, proxy=proxy,
                                   timeout=(5.0, 30.0), follow_redirects=True,
                                   transport=transport)
        self.async_client = None

    def close(self):
        self.client.close()

    def ensure_async_client(self):
        if self.async_client is None:
            self.async_client = httpx.AsyncClient(headers=self.headers, proxy=self.proxies,
                                                  timeout=(3.05, 16.0), follow_redirects=True,
                                                  transport=self._transport)
        return self.async_client

    async def aclose(self):
        if self.async_client is not None:
            await self.async_client.aclose()
            self.async_client = None

    def get_json(self, url, retries=5):
        """同步 API 调用:网络错误/5xx 退避重试;配额耗尽立即抛 RateLimitError;
        401/403 抛 AuthError;其余抛 TwitterAPIError。"""
        last_err = None
        for attempt in range(retries):
            try:
                response = self.client.get(quote_url(url))
            except httpx.RequestError as e:
                last_err = e
                if isinstance(e, httpx.ConnectError) and attempt >= 1:
                    # 连接层故障(DNS/拒绝连接):重试 1 次仍失败即快速抛错,
                    # 让调用方尽早决策——重试满 5 次最坏空等 ~62s
                    raise TwitterAPIError(f'连接失败,重试后仍无法连接: {e}') from e
                wait = 2 * (2 ** attempt)
                logger.warning(f'网络请求失败({type(e).__name__}): {e}, {wait}s 后重试(第 {attempt + 1}/{retries} 次)')
                time.sleep(wait)
                continue

            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    raise TwitterAPIError('响应不是合法 JSON', 200, response.text[:500])

            if response.status_code in (401, 403):
                raise AuthError('认证失败,请检查 cookie(auth_token/ct0)', response.status_code, response.text[:500])

            if response.status_code == 429 or (response.status_code != 200 and 'Rate limit exceeded' in response.text):
                # 注意:仅在非 200 响应里匹配限流文本——200 响应体里的推文内容可能恰好含该字样,误判会中止整个任务
                if 'Rate limit exceeded' in response.text:
                    raise RateLimitError('API 次数已超限(当日配额耗尽)', 429, response.text[:500])
                # 无配额提示的 429:瞬时限流,退避重试
                last_err = RateLimitError('HTTP 429', 429, response.text[:500])
                time.sleep(2 * (2 ** attempt))
                continue

            if response.status_code >= 500:
                last_err = TwitterAPIError(f'服务端错误 {response.status_code}', response.status_code, response.text[:500])
                logger.warning(f'服务端错误 {response.status_code}, 重试中(第 {attempt + 1}/{retries} 次)')
                time.sleep(2 * (2 ** attempt))
                continue

            raise TwitterAPIError(f'HTTP {response.status_code}', response.status_code, response.text[:500])

        # 重试耗尽:仅真实配额类失败抛 RateLimitError,网络/服务端故障抛 TwitterAPIError——
        # 否则一次网络抖动会让调用方误判为「当日配额耗尽」而中止整个批量任务
        if isinstance(last_err, TwitterAPIError):
            raise last_err
        raise TwitterAPIError(f'请求重试 {retries} 次仍失败: {last_err}')
