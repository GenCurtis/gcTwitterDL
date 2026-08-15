# -*- coding: utf-8 -*-
# main.py / sync_down.py 的配置加载(借鉴 nhentai-dl:单例 + 脏配置容错,绝不因配置崩溃)
import json
import os
import re
from pathlib import Path

from .utils import time2stamp
from .logger import logger

# 默认配置(settings.json 缺键时的回退值)
DEFAULTS = {
    'save_path': '',
    'user_lst': '',
    'cookie': '',
    'has_retweet': False,
    'high_lights': False,
    'likes': False,
    'time_range': '',
    'autoSync': False,
    'down_log': False,
    'image_format': 'orig',
    'has_video': False,
    'log_output': False,
    'max_concurrent_requests': 8,
    'proxy': '',
    'md_output': True,
    'media_count_limit': 0,
    'content_dedup': True,
}

# 仓库根目录(本文件上两级);save_path 留空时的默认下载目录
REPO_ROOT = Path(__file__).resolve().parent.parent


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class Config:
    def __init__(self, settings_path='settings.json', users_path='users.json'):
        self.settings_path = settings_path
        self.users_path = users_path
        self.raw = {}
        self.users_raw = {}
        self._load()

    def _load(self):
        self.raw = self._load_json(self.settings_path)
        self.users_raw = self._load_json(self.users_path)

        # save_path:兼容 Windows 反斜杠路径(统一转正斜杠);留空默认 <仓库根>/downloads
        raw_path = self.raw.get('save_path', DEFAULTS['save_path'])
        if not raw_path:
            self.save_path = str(REPO_ROOT / 'downloads')
        else:
            self.save_path = re.sub('/+', '/', str(raw_path).replace('\\', '/')).rstrip('/')

        # user_lst 优先取 users.json(不进 git,名单/别名独立管理);settings.json 的 user_lst 仅作迁移兜底
        self.user_lst = self.users_raw.get('user_lst', self.raw.get('user_lst', DEFAULTS['user_lst']))
        alias = self.users_raw.get('alias', {})
        self.alias = alias if isinstance(alias, dict) else {}
        self.cookie = self.raw.get('cookie', DEFAULTS['cookie'])
        self.time_range = self.raw.get('time_range', DEFAULTS['time_range'])

        # 三个模式互斥:high_lights / likes 会覆盖其余选项
        self.has_retweet = bool(self.raw.get('has_retweet', DEFAULTS['has_retweet']))
        self.has_highlights = bool(self.raw.get('high_lights', DEFAULTS['high_lights']))
        self.has_likes = bool(self.raw.get('likes', DEFAULTS['likes']))
        if self.has_highlights:
            self.has_retweet = False
        if self.has_likes:
            self.has_retweet = True
            self.has_highlights = False

        self.autoSync = bool(self.raw.get('autoSync', DEFAULTS['autoSync']))
        self.down_log = bool(self.raw.get('down_log', DEFAULTS['down_log']))
        self.has_video = bool(self.raw.get('has_video', DEFAULTS['has_video']))
        self.log_output = bool(self.raw.get('log_output', DEFAULTS['log_output']))
        self.md_output = bool(self.raw.get('md_output', DEFAULTS['md_output']))
        self.content_dedup = bool(self.raw.get('content_dedup', DEFAULTS['content_dedup']))
        self.max_concurrent_requests = max(1, _safe_int(self.raw.get('max_concurrent_requests'), DEFAULTS['max_concurrent_requests']))
        self.media_count_limit = max(0, _safe_int(self.raw.get('media_count_limit'), DEFAULTS['media_count_limit']))
        self.proxies = self.raw.get('proxy', DEFAULTS['proxy']) or None

        # 图片格式:orig = 原图(按扩展名保存,404 时降级 4096x4096);jpg/png = 强制格式
        img_fmt = self.raw.get('image_format', DEFAULTS['image_format'])
        self.orig_format = img_fmt == 'orig'
        self.img_format = 'jpg' if self.orig_format else img_fmt

        # 时间范围(毫秒时间戳);likes 模式强制全量
        self.start_stamp = 655028357000    # 1990-10-04
        self.end_stamp = 2548484357000     # 2050-10-04
        if self.time_range and not self.has_likes:
            try:
                start_time, end_time = self.time_range.split(':')
                self.start_stamp, self.end_stamp = time2stamp(start_time), time2stamp(end_time)
            except (ValueError, IndexError) as e:
                logger.warning(f'time_range 格式错误(应为 YYYY-MM-DD:YYYY-MM-DD): {self.time_range},已使用无限制。错误: {e}')

    def _load_json(self, path):
        """读取 JSON 配置文件;非法 JSON 时容错:把裸反斜杠(手抄 Windows 路径)替换为正斜杠再解析"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    text = f.read()
                fixed = text.replace('\\', '/')
                data = json.loads(fixed)
                logger.warning(f'{path} 含非法转义(裸反斜杠路径),已自动修复为 / 后解析')
                return data
            except Exception:
                logger.warning(f'读取 {path} 失败,将使用默认值。错误: {e}')
                return {}
        except Exception as e:
            logger.warning(f'读取 {path} 失败,将使用默认值。错误: {e}')
            return {}

    def save_users(self):
        """原子写回 users.json(CLI 的 add/remove/alias 使用);保留 *_info 注释键"""
        tmp = self.users_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.users_raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.users_path)

    def add_users(self, names):
        """加入名单(去重、去空白);返回实际新增的用户名列表"""
        lst = self.user_list
        added = []
        for n in names:
            n = str(n).strip()
            if n and n not in lst:
                lst.append(n)
                added.append(n)
        if added:
            self.users_raw['user_lst'] = lst
            self.save_users()
        return added

    def remove_users(self, names):
        """从名单移除;返回实际移除的用户名列表"""
        lst = self.user_list
        removed = [str(n).strip() for n in names if str(n).strip() in lst]
        if removed:
            self.users_raw['user_lst'] = [u for u in lst if u not in removed]
            self.save_users()
        return removed

    def set_alias(self, group, members):
        """设置别名组(组名 -> 成员列表);组名/成员去空白。返回组成员列表"""
        members = [str(m).strip() for m in members if str(m).strip()]
        self.users_raw['alias'][group] = members
        self.save_users()
        return members

    @property
    def user_list(self):
        # 支持三种写法:逗号分隔字符串 / 换行(含 \n 转义)分隔字符串 / JSON 数组
        # 数据源:users.json 优先(见 _load),settings.json 的 user_lst 仅迁移兜底
        lst = self.user_lst
        if isinstance(lst, list):
            return [str(u).strip() for u in lst if str(u).strip()]
        return [u for u in re.split(r'[,\s]+', str(lst)) if u]


config = Config()
