# -*- coding: utf-8 -*-
# 通用工具函数:URL 转义、时间戳、推文时间解析、媒体质量选择、请求头构造
import re
import time
import hashlib
from datetime import datetime

from .logger import logger

# 固定 UA 与公共 Bearer token(取自 x.com 网页端,失效需整体更新)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
BEARER = 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'

# 封号/注销用户 result.__typename 枚举(可能漂移,未命中但 result 为 None 时按 not_found 保守处理)
SUSPENDED_TYPES = ('UserUnavailable', 'UserTombstone', 'UserUnavailableTombstone')
KNOWN_OK_TYPES = ('User',)


def quote_url(url):
    # httpx 拒绝 URL 中的裸花括号,统一转义
    return url.replace('{', '%7B').replace('}', '%7D')


def del_special_char(string, keep='#'):
    # 过滤非法文件名字符,保留中日英数字与点号(keep 可额外保留字符,如 tag 的 #)
    chars = '\u4e00-\u9fa5\u0030-\u0039\u0041-\u005a\u0061-\u007a\u3040-\u31FF.' + keep
    return re.sub(f'[^{chars}]', '', string)


def stamp2time(msecs_stamp):
    # 毫秒时间戳 -> 本地时间字符串(文件名/CSV 用)
    timeArray = time.localtime(msecs_stamp / 1000)
    return time.strftime('%Y-%m-%d %H-%M', timeArray)


def time2stamp(timestr):
    # 'YYYY-MM-DD' -> 毫秒时间戳
    datetime_obj = datetime.strptime(timestr, '%Y-%m-%d')
    msecs_stamp = int(time.mktime(datetime_obj.timetuple()) * 1000.0 + datetime_obj.microsecond / 1000.0)
    return msecs_stamp


def time_comparison(now, start, end):
    # twitter 时间线由新到旧:命中区间则下载,早于区间则停止
    start_down = start <= now <= end
    start_label = now >= start
    return [start_down, start_label]


def get_tweet_msecs(result):
    # 从推文结果中取发布时间毫秒:优先精确时间(legacy.created_at,秒级,UTC);
    # 缺失/格式变动时回退 edit_control 近似(editable_until - 1h,±30min 误差);全部失败返回 None
    # ponytail: created_at 解析失败静默回退,不改调用方
    try:
        dt = datetime.strptime(result['legacy']['created_at'], '%a %b %d %H:%M:%S %z %Y')
        return int(dt.timestamp() * 1000)
    except Exception:
        pass
    try:
        ts = int(result['edit_control']['editable_until_msecs']) - 3600000
        if ts > 0:
            return ts
    except Exception:
        pass
    try:
        ts = int(result['edit_control']['edit_control_initial']['editable_until_msecs']) - 3600000
        if ts > 0:
            return ts
    except Exception:
        pass
    return None


def check_user_status(result):
    """统一封号/注销/不存在判定(替代 main/sync_down 两份重复逻辑)。
    返回 'ok' / 'suspended' / 'not_found';
    未知 __typename 打 warning 留痕(枚举漂移时日志可直接定位)。"""
    if result is None:
        return 'not_found'
    typename = result.get('__typename', '')
    if typename in SUSPENDED_TYPES:
        return 'suspended'
    if typename not in KNOWN_OK_TYPES:
        logger.warning(f'未知 __typename: {typename!r},请核对封号枚举/响应结构')
    return 'ok'


def extract_latest_media_id(raw_data):
    """从 UserMedia 第一页响应中提取最新媒体推文 ID(snowflake,单调递增)。
    推文 ID 是时间的有序代理:比数量类信号(statuses_count/media_count)可靠——
    用户「删一条发一条」时数量不变但 ID 必然变大。
    返回 None 表示无媒体推文或结构异常(调用方应保守处理,不可当作「无变化」)。"""
    try:
        instructions = raw_data['data']['user']['result']['timeline_v2']['timeline']['instructions']
        entries = instructions[-1].get('entries', [])
    except (KeyError, TypeError, IndexError):
        return None

    for entry in entries:
        eid = entry.get('entryId', '')
        if 'promoted' in eid or 'cursor' in eid or 'pin' in eid:
            continue
        try:
            # 第一页 UserMedia:媒体在 timeline-module 条目的 content.items 里(与 main.py 的 First_Page 处理一致)
            items = entry['content']['items']
            for item in items:
                try:
                    result = item['item']['itemContent']['tweet_results']['result']
                    if 'tweet' in result:
                        result = result['tweet']
                    return int(result['rest_id'])
                except (KeyError, TypeError, ValueError):
                    continue
            continue
        except (KeyError, TypeError):
            pass
        # 常规 tweet 条目(后续页结构,兜底)
        try:
            result = entry['content']['itemContent']['tweet_results']['result']
            if 'tweet' in result:
                result = result['tweet']
            return int(result['rest_id'])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def get_highest_video_quality(variants):
    # 找最高码率视频地址;单 variant(gif)直接返回
    if len(variants) == 1:
        return variants[0]['url']
    max_bitrate = 0
    heighest_url = None
    for i in variants:
        if 'bitrate' in i and int(i['bitrate']) > max_bitrate:
            max_bitrate = int(i['bitrate'])
            heighest_url = i['url']
    return heighest_url


def hash_save_token(media_url):
    # 媒体文件名去重后缀:md5 前 8 位(4 位在 10³ 媒体量级碰撞 ~1.5%,8 位在 10⁵ 量级前可忽略)
    m = hashlib.md5()
    m.update(media_url.encode('utf-8'))
    return m.hexdigest()[:8]


def build_headers(cookie):
    # 构造 API 请求头;ct0 缺失时抛 ValueError(缺少它所有请求都会 401)
    _headers = {
        'user-agent': UA,
        'authorization': BEARER,
    }
    if cookie:
        _headers['cookie'] = cookie
        csrf = re.findall(r'ct0=([^;\s]+)', cookie)
        if not csrf:
            raise ValueError('cookie 缺少 ct0 字段(格式应为 "ct0=xxx;")')
        _headers['x-csrf-token'] = csrf[0]
    else:
        raise ValueError('cookie 为空,请先配置 cookie(auth_token 与 ct0)')
    return _headers
