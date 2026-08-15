# -*- coding: utf-8 -*-
import json
import os

from tw_dl.config import Config, REPO_ROOT

def _cfg(tmp_path, p=None):
    """隔离 users.json:测试不读仓库根的真实名单文件"""
    return Config(p if p is not None else str(tmp_path / 'settings.json'),
                  users_path=str(tmp_path / 'users.json'))



def _write_settings(tmp_path, data):
    p = tmp_path / 'settings.json'
    p.write_text(json.dumps(data), encoding='utf-8')
    return str(p)


def test_basic_parsing(tmp_path):
    p = _write_settings(tmp_path, {
        'save_path': 'C:/downloads', 'user_lst': 'a,b,c', 'cookie': 'auth_token=x; ct0=y;',
        'time_range': '2020-01-01:2024-01-01', 'max_concurrent_requests': '16',
    })
    cfg = _cfg(tmp_path, p)
    assert cfg.save_path == 'C:/downloads'
    assert cfg.user_list == ['a', 'b', 'c']
    assert cfg.max_concurrent_requests == 16
    assert cfg.start_stamp < cfg.end_stamp


def test_invalid_int_falls_back(tmp_path):
    p = _write_settings(tmp_path, {'max_concurrent_requests': 'abc'})
    cfg = _cfg(tmp_path, p)
    assert cfg.max_concurrent_requests == 8


def test_concurrency_clamped_min_1(tmp_path):
    # 0 或负数会让 asyncio.Semaphore 抛 ValueError,钳位到 1
    cfg = _cfg(tmp_path, _write_settings(tmp_path, {'max_concurrent_requests': 0}))
    assert cfg.max_concurrent_requests == 1
    cfg = _cfg(tmp_path, _write_settings(tmp_path, {'max_concurrent_requests': -5}))
    assert cfg.max_concurrent_requests == 1


def test_media_count_limit_clamped_non_negative(tmp_path):
    cfg = _cfg(tmp_path, _write_settings(tmp_path, {'media_count_limit': -1}))
    assert cfg.media_count_limit == 0
    cfg = _cfg(tmp_path, _write_settings(tmp_path, {'media_count_limit': 3}))
    assert cfg.media_count_limit == 3


def test_malformed_time_range_uses_unlimited(tmp_path):
    # 多于一个冒号 → 解析失败回退全量,不崩溃
    cfg = _cfg(tmp_path, _write_settings(tmp_path, {'time_range': '2020-01-01:2024-01-01:extra'}))
    assert cfg.start_stamp == 655028357000
    assert cfg.end_stamp == 2548484357000
    cfg = _cfg(tmp_path, _write_settings(tmp_path, {'time_range': 'not-a-date'}))
    assert cfg.start_stamp == 655028357000


def test_empty_user_lst(tmp_path):
    cfg = _cfg(tmp_path, _write_settings(tmp_path, {'user_lst': ''}))
    assert cfg.user_list == []


def test_proxy_empty_is_none(tmp_path):
    cfg = _cfg(tmp_path, _write_settings(tmp_path, {'proxy': ''}))
    assert cfg.proxies is None
    cfg = _cfg(tmp_path, _write_settings(tmp_path, {'proxy': 'http://127.0.0.1:7890'}))
    assert cfg.proxies == 'http://127.0.0.1:7890'


def test_empty_save_path_uses_downloads(tmp_path):
    p = _write_settings(tmp_path, {'save_path': ''})
    cfg = _cfg(tmp_path, p)
    assert cfg.save_path == str(REPO_ROOT / 'downloads')


def test_windows_backslash_path_normalized(tmp_path):
    # 合法 JSON 转义的反斜杠路径(JSON 中为 \\) → 归一化为正斜杠
    p = _write_settings(tmp_path, {'save_path': 'C:\\downloads\\x'})
    cfg = _cfg(tmp_path, p)
    assert cfg.save_path == 'C:/downloads/x'


def test_windows_double_backslash_collapsed(tmp_path):
    p = _write_settings(tmp_path, {'save_path': 'C:\\\\downloads\\\\'})
    cfg = _cfg(tmp_path, p)
    assert cfg.save_path == 'C:/downloads'


def test_orig_format(tmp_path):
    p = _write_settings(tmp_path, {'image_format': 'orig'})
    cfg = _cfg(tmp_path, p)
    assert cfg.orig_format is True and cfg.img_format == 'jpg'


def test_jpg_format(tmp_path):
    p = _write_settings(tmp_path, {'image_format': 'jpg'})
    cfg = _cfg(tmp_path, p)
    assert cfg.orig_format is False and cfg.img_format == 'jpg'


def test_likes_overrides_others_and_ignores_range(tmp_path):
    p = _write_settings(tmp_path, {'likes': True, 'high_lights': True, 'has_retweet': True,
                                   'time_range': '2020-01-01:2024-01-01'})
    cfg = _cfg(tmp_path, p)
    assert cfg.has_likes is True and cfg.has_retweet is True and cfg.has_highlights is False
    assert cfg.start_stamp == 655028357000  # 全量


def test_highlights_disables_retweet(tmp_path):
    p = _write_settings(tmp_path, {'high_lights': True, 'has_retweet': True})
    cfg = _cfg(tmp_path, p)
    assert cfg.has_highlights is True and cfg.has_retweet is False


def test_missing_file_uses_defaults(tmp_path):
    cfg = _cfg(tmp_path, str(tmp_path / 'nope.json'))
    assert cfg.save_path == str(REPO_ROOT / 'downloads')
    assert cfg.user_lst == ''
    assert cfg.orig_format is True


def test_user_lst_as_json_array(tmp_path):
    p = _write_settings(tmp_path, {'user_lst': ['a', ' b ', '', 'c']})
    cfg = _cfg(tmp_path, p)
    assert cfg.user_list == ['a', 'b', 'c']


def test_user_lst_newline_separated(tmp_path):
    p = _write_settings(tmp_path, {'user_lst': 'a,\nb\nc'})
    cfg = _cfg(tmp_path, p)
    assert cfg.user_list == ['a', 'b', 'c']


def test_invalid_json_backslash_fixed(tmp_path):
    # 手抄 Windows 路径产生的非法 JSON(裸反斜杠)→ 容错为正斜杠后解析
    p = tmp_path / 'settings.json'
    p.write_text('{"save_path": "C:\\downloads\\x", "user_lst": "a"}', encoding='utf-8')
    cfg = _cfg(tmp_path, str(p))
    assert cfg.save_path == 'C:/downloads/x'
    assert cfg.user_list == ['a']


def test_users_json_takes_priority(tmp_path):
    # users.json 的 user_lst 优先于 settings.json(名单独立管理)
    p = _write_settings(tmp_path, {'user_lst': 'from_settings'})
    users = tmp_path / 'users.json'
    users.write_text(json.dumps({'user_lst': ['from_users']}), encoding='utf-8')
    cfg = _cfg(tmp_path, p)
    cfg.users_path = str(users)
    cfg.users_raw = json.loads(users.read_text(encoding='utf-8'))
    assert cfg.user_list == ['from_users']


def test_settings_user_lst_fallback(tmp_path):
    # users.json 缺失/无 user_lst → settings.json 兜底(迁移兼容)
    p = _write_settings(tmp_path, {'user_lst': 'a,b'})
    cfg = _cfg(tmp_path, p)
    assert cfg.user_list == ['a', 'b']


def test_alias_parsing(tmp_path):
    p = _write_settings(tmp_path, {})
    users = tmp_path / 'users.json'
    users.write_text(json.dumps({'user_lst': ['a'], 'alias': {'组': ['a', 'b']}}), encoding='utf-8')
    cfg = _cfg(tmp_path, p)
    cfg.users_path = str(users)
    cfg.users_raw = json.loads(users.read_text(encoding='utf-8'))
    cfg._load()
    assert cfg.alias == {'组': ['a', 'b']}


def test_invalid_alias_type_ignored(tmp_path):
    p = _write_settings(tmp_path, {})
    users = tmp_path / 'users.json'
    users.write_text(json.dumps({'user_lst': [], 'alias': 'not-a-dict'}), encoding='utf-8')
    cfg = _cfg(tmp_path, p)
    cfg.users_path = str(users)
    cfg.users_raw = json.loads(users.read_text(encoding='utf-8'))
    cfg._load()
    assert cfg.alias == {}


def test_add_users_dedupes_and_persists(tmp_path):
    # add:去重、保留注释键、原子落盘,重载后生效
    p = _write_settings(tmp_path, {})
    users = tmp_path / 'users.json'
    users.write_text(json.dumps({'user_lst': ['a'], 'alias': {}, 'info_note': '保留'}), encoding='utf-8')
    cfg = _cfg(tmp_path, p)
    cfg.users_path = str(users)
    cfg.users_raw = json.loads(users.read_text(encoding='utf-8'))
    assert cfg.add_users(['b', 'a', ' c ', '']) == ['b', 'c']
    assert not os.path.exists(str(users) + '.tmp')

    cfg2 = _cfg(tmp_path, p)
    cfg2.users_path = str(users)
    cfg2.users_raw = json.loads(users.read_text(encoding='utf-8'))
    assert cfg2.user_list == ['a', 'b', 'c']
    assert cfg2.users_raw['info_note'] == '保留'


def test_remove_users(tmp_path):
    p = _write_settings(tmp_path, {})
    users = tmp_path / 'users.json'
    users.write_text(json.dumps({'user_lst': ['a', 'b', 'c']}), encoding='utf-8')
    cfg = _cfg(tmp_path, p)
    cfg.users_path = str(users)
    cfg.users_raw = json.loads(users.read_text(encoding='utf-8'))
    assert cfg.remove_users(['a', 'nope']) == ['a']
    cfg2 = _cfg(tmp_path, p)
    cfg2.users_path = str(users)
    cfg2.users_raw = json.loads(users.read_text(encoding='utf-8'))
    assert cfg2.user_list == ['b', 'c']


def test_set_alias_persists(tmp_path):
    p = _write_settings(tmp_path, {})
    users = tmp_path / 'users.json'
    users.write_text(json.dumps({'user_lst': ['a'], 'alias': {}}), encoding='utf-8')
    cfg = _cfg(tmp_path, p)
    cfg.users_path = str(users)
    cfg.users_raw = json.loads(users.read_text(encoding='utf-8'))
    cfg.set_alias('组名', ['a', ' b ', ''])
    cfg2 = _cfg(tmp_path, p)
    cfg2.users_path = str(users)
    cfg2.users_raw = json.loads(users.read_text(encoding='utf-8'))
    assert cfg2.alias == {'组名': ['a', 'b']}
