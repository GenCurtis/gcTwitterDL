# -*- coding: utf-8 -*-
# 媒体下载核心(合并原 main/tag/reply 三个 download_control):
# - 单一共享 AsyncClient,不再每文件建连接
# - 404 处理:orig 模式降级 4096x4096 重试一次;其余 404/403/410 直接放弃(原实现会无限重试)
# - 网络错误/其他状态码:退避重试至上限,到达上限跳过该文件
# - 原子落盘:先写 .tmp 再 rename,中断不留半文件
# - 可选内容级去重(dedup):同用户/同组完全一致内容只保留时间戳最早的一份
import asyncio
import hashlib
import os

import httpx

from .utils import quote_url
from .logger import logger


class MediaFetchError(Exception):
    pass


def get_fallback_url(url):
    # 404 降级地址:仅 orig 模式(name=orig)可降级;无降级返回 None(直接放弃)
    if 'name=orig' in url:
        return url.replace('name=orig', 'name=4096x4096')
    return None


async def fetch_media(client, url, fallback=True, max_retries=50):
    """下载媒体内容;404 时按降级规则重试一次;网络错误退避重试至 max_retries。"""
    current, fallback_done = url, False
    for attempt in range(1, max_retries + 1):
        try:
            response = await client.get(quote_url(current))
        except httpx.RequestError as e:
            if attempt >= max_retries:
                break
            logger.warning(f'{current} 网络错误({type(e).__name__}): {e},第 {attempt} 次重试')
            await asyncio.sleep(1.0)
            continue

        if response.status_code == 200:
            return response.content

        if response.status_code == 404:
            if not fallback_done and fallback:
                fb = get_fallback_url(current)
                if fb:
                    current, fallback_done = fb, True
                    logger.warning(f'{url} 404,降级重试: {fb}')
                    continue
            raise MediaFetchError(f'{current} 返回 404')

        if response.status_code in (403, 410):
            # 永久性失败(地区/版权限制、资源已删除):重试无意义,立即放弃
            raise MediaFetchError(f'{current} 返回 {response.status_code}(永久性失败)')

        if attempt >= max_retries:
            break
        logger.warning(f'{current} HTTP {response.status_code},第 {attempt} 次重试')
        await asyncio.sleep(1.0)

    raise MediaFetchError(f'{url} 重试 {max_retries} 次仍失败')


async def download_many(api, jobs, max_concurrent=8, pre_hook=None, post_hook=None, dedup=None):
    """并发下载媒体列表并保存文件。
    jobs: [(url, filename, fallback, extra), ...],extra 为透传参数(如 csv_info)
    pre_hook(url, filename, extra): 下载前调用(md 预写,保证推文顺序)
    post_hook(url, filename, extra): 保存成功后调用(csv 写入等;去重丢弃时也调用,记录推文事实)
    dedup(DedupIndex|None): 内容级去重,返回 'drop' 时不落盘
    返回失败列表 [(url, filename, err), ...]
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    failed = []

    async def worker(job):
        url, filename, fallback, extra = job
        try:
            if pre_hook:
                pre_hook(url, filename, extra)
            async with semaphore:
                content = await fetch_media(api.async_client, url, fallback=fallback)
            if dedup:
                md5 = hashlib.md5(content).hexdigest()
                if dedup.decide(md5, filename) == 'drop':
                    if post_hook:
                        post_hook(url, filename, extra)  # CSV 照写:记录该推文有该媒体的事实
                    return
            tmp_name = filename + '.tmp'
            with open(tmp_name, 'wb') as f:
                f.write(content)
            os.replace(tmp_name, filename)  # 原子落盘:中断不留半文件
            if post_hook:
                post_hook(url, filename, extra)
        except Exception as e:
            logger.error(f'{filename} 下载失败,已跳过: {e}')
            failed.append((url, filename, e))

    await asyncio.gather(*[worker(job) for job in jobs])
    return failed
