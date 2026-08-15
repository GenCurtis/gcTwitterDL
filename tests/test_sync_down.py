# -*- coding: utf-8 -*-
# sync_down 变化侦测判定:latest <= prev 跳过(删帖回退不再触发空增量)、
# 新帖触发、首次建基线、封号归档、注销跳过、失败不记状态
import json

import pytest

import sync_down


def _media_raw(latest_id, typename='User'):
    result = {'__typename': typename}
    if typename == 'User':
        result['timeline_v2'] = {'timeline': {'instructions': [{'entries': [
            {'entryId': 'timeline-module-1', 'content': {'items': [
                {'item': {'itemContent': {'tweet_results': {'result': {'rest_id': str(latest_id)}}}}}]}},
        ]}]}}
    return {'data': {'user': {'result': result}}}


def _user_raw(rest_id='123', name='缓存昵称'):
    return {'data': {'user': {'result': {'__typename': 'User', 'rest_id': rest_id,
                                         'legacy': {'name': name, 'statuses_count': 1, 'media_count': 1}}}}}


def _state(env, data):
    (env / '_sync_state.json').write_text(json.dumps(data), encoding='utf-8')


def _read_state(env):
    return json.loads((env / '_sync_state.json').read_text(encoding='utf-8'))


class FakeAPI:
    payloads = []

    def __init__(self, cookie, proxy=None):
        pass

    def get_json(self, url):
        return self.payloads.pop(0)

    def close(self):
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_down, 'STATE_FILE', str(tmp_path / '_sync_state.json'))
    monkeypatch.setattr(sync_down.config, 'save_path', str(tmp_path))
    monkeypatch.setattr(sync_down.config, 'cookie', 'auth_token=x; ct0=y;')
    monkeypatch.setattr(sync_down.config, 'proxies', None)
    monkeypatch.setattr(sync_down.config, 'user_lst', 'u1')  # user_list 是实例属性拷贝
    monkeypatch.setattr(sync_down.config, 'alias', {})
    monkeypatch.setattr(sync_down, 'TwitterAPI', FakeAPI)
    FakeAPI.payloads = []
    return tmp_path


def test_skips_when_latest_decreased(env, monkeypatch):
    # R9 回归:删帖使最新媒体 ID 回退(latest < prev)→ 不触发空增量,状态保留
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500}})
    FakeAPI.payloads = [_media_raw(400)]
    called = []
    monkeypatch.setattr(sync_down, 'main', lambda ui: called.append(ui.screen_name) or True)
    sync_down.sync()
    assert called == []
    # prev 保持 500:之后任何新帖 ID > 500 仍会正常触发
    assert _read_state(env)['u1']['latest_media_id'] == 500


def test_skips_when_latest_equal(env, monkeypatch):
    # 无新媒体:相等也跳过(原有行为不破坏)
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500}})
    FakeAPI.payloads = [_media_raw(500)]
    called = []
    monkeypatch.setattr(sync_down, 'main', lambda ui: called.append(1) or True)
    sync_down.sync()
    assert called == []


def test_triggers_when_latest_increased(env, monkeypatch):
    # 新帖(latest > prev):触发增量并更新状态
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500}})
    FakeAPI.payloads = [_media_raw(600)]
    called = []
    monkeypatch.setattr(sync_down, 'main', lambda ui: called.append(ui.screen_name) or True)
    sync_down.sync()
    assert called == ['u1']
    st = _read_state(env)['u1']
    assert st['rest_id'] == '123' and st['latest_media_id'] == 600


def test_delete_then_post_new_still_triggers(env, monkeypatch):
    # 「删一条发一条」:最新 ID > prev 仍触发(数量类信号会漏,ID 比较不丢)
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500}})
    FakeAPI.payloads = [_media_raw(900)]  # 删了旧的、发了新的:最新 ID 必然更大
    called = []
    monkeypatch.setattr(sync_down, 'main', lambda ui: called.append(1) or True)
    sync_down.sync()
    assert called == [1]


def test_first_sync_builds_baseline(env, monkeypatch):
    # 首次(无状态):UserByScreenName 拿 rest_id + UserMedia → 触发并建基线
    FakeAPI.payloads = [_user_raw(), _media_raw(700)]
    called = []
    monkeypatch.setattr(sync_down, 'main', lambda ui: called.append(ui.screen_name) or True)
    sync_down.sync()
    assert called == ['u1']
    st = _read_state(env)['u1']
    assert st['rest_id'] == '123' and st['latest_media_id'] == 700
    assert 'checked_at' in st


def test_state_stores_name_for_main_cache(env, monkeypatch):
    # name 一并写入状态(main.py 全量模式读此字段可省 UserByScreenName 调用)
    FakeAPI.payloads = [_user_raw(name='昵称A'), _media_raw(700)]
    monkeypatch.setattr(sync_down, 'main', lambda ui: True)
    sync_down.sync()
    st = _read_state(env)['u1']
    assert st['name'] == '昵称A'


def test_no_media_tweets_skipped_conservatively(env, monkeypatch):
    # 无媒体推文(latest 解析为 None):保守跳过,不触发
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500}})
    FakeAPI.payloads = [_media_raw(None, 'User')]  # entries 为空 → 解析不到 ID
    called = []
    monkeypatch.setattr(sync_down, 'main', lambda ui: called.append(1) or True)
    sync_down.sync()
    assert called == []


def test_suspended_user_archived_and_state_removed(env, monkeypatch):
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500}})
    FakeAPI.payloads = [_media_raw(None, 'UserUnavailable')]
    archived = []
    monkeypatch.setattr(sync_down, 'archive_suspended_user', lambda u, p: archived.append(u))
    monkeypatch.setattr(sync_down, 'main', lambda ui: True)
    sync_down.sync()
    assert archived == ['u1']
    assert 'u1' not in _read_state(env)


def test_not_found_with_history_archived(env, monkeypatch):
    # R10:曾有 rest_id 历史的用户取不到信息(result=None)→ 疑似封号/注销,归档并删状态
    # (免疫封号枚举漂移:枚举改名时「曾经存在 + 现在消失」仍成立)
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500}})
    FakeAPI.payloads = [{'data': {'user': {'result': None}}}]
    archived = []
    monkeypatch.setattr(sync_down, 'archive_suspended_user', lambda u, p: archived.append(u))
    monkeypatch.setattr(sync_down, 'main', lambda ui: True)
    sync_down.sync()
    assert archived == ['u1']
    assert 'u1' not in _read_state(env)


def test_not_found_without_history_skipped(env, monkeypatch):
    # 无历史记录(首次/拼错用户名)→ 不归档、不触发
    FakeAPI.payloads = [{'data': {'user': {'result': None}}}]
    archived = []
    called = []
    monkeypatch.setattr(sync_down, 'archive_suspended_user', lambda u, p: archived.append(u))
    monkeypatch.setattr(sync_down, 'main', lambda ui: called.append(1) or True)
    sync_down.sync()
    assert archived == []
    assert called == []
    assert not (env / '_sync_state.json').exists()


def test_detection_error_skipped(env, monkeypatch):
    # API 错误(网络/结构):回退 UserByScreenName 重建 rest_id 仍无新内容 → 跳过
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500}})
    # 第一次 UserMedia 结构异常 → 重建(UserByScreenName)→ UserMedia 返回 latest=400(回退)→ 跳过
    FakeAPI.payloads = [{'unexpected': 'structure'}, _user_raw(), _media_raw(400)]
    called = []
    monkeypatch.setattr(sync_down, 'main', lambda ui: called.append(1) or True)
    sync_down.sync()
    assert called == []
    assert _read_state(env)['u1']['latest_media_id'] == 500


def test_main_failure_does_not_update_state(env, monkeypatch):
    # main 返回 False(配额/中断)→ 状态不更新,下次重试
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500}})
    FakeAPI.payloads = [_media_raw(600)]
    monkeypatch.setattr(sync_down, 'main', lambda ui: False)
    sync_down.sync()
    assert _read_state(env)['u1']['latest_media_id'] == 500


def test_main_structure_error_state_not_updated(env, monkeypatch):
    # R6.2 集成:main 因响应结构异常抛错(R6.2 改造后) → 状态不更新,下次重试
    from tw_dl.api import ResponseStructureError
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500}})
    FakeAPI.payloads = [_media_raw(600)]

    def boom(ui):
        ui.last_error = 'structure'
        raise ResponseStructureError('响应结构解析失败')

    monkeypatch.setattr(sync_down, 'main', boom)
    sync_down.sync()  # 不崩溃:sync 对 main 调用有 try/except
    assert _read_state(env)['u1']['latest_media_id'] == 500


def test_structural_failure_continues_other_users(env, monkeypatch):
    # C1:结构异常(个体性)→ 不 break,继续处理后续用户
    monkeypatch.setattr(sync_down.config, 'user_lst', 'u1,u2')
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500},
                 'u2': {'rest_id': '456', 'latest_media_id': 500}})
    FakeAPI.payloads = [_media_raw(600), _media_raw(700)]  # 两个用户都有变化
    called = []

    def fake_main(ui):
        called.append(ui.screen_name)
        if ui.screen_name == 'u1':
            ui.last_error = 'structure'  # u1 结构异常
            return False
        return True

    monkeypatch.setattr(sync_down, 'main', fake_main)
    sync_down.sync()
    assert called == ['u1', 'u2']  # u2 仍被处理
    st = _read_state(env)
    assert 'u1' not in st or st['u1']['latest_media_id'] == 500  # u1 未更新
    assert st['u2']['latest_media_id'] == 700                     # u2 已更新


def test_quota_failure_breaks_loop(env, monkeypatch):
    # 配额(全局性)→ break,后续用户不再处理
    monkeypatch.setattr(sync_down.config, 'user_lst', 'u1,u2')
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500},
                 'u2': {'rest_id': '456', 'latest_media_id': 500}})
    FakeAPI.payloads = [_media_raw(600), _media_raw(700)]
    called = []

    def fake_main(ui):
        called.append(ui.screen_name)
        ui.last_error = 'rate_limit'
        return False

    monkeypatch.setattr(sync_down, 'main', fake_main)
    sync_down.sync()
    assert called == ['u1']  # u2 被跳过


def test_missing_cookie_aborts(env, monkeypatch):
    monkeypatch.setattr(sync_down.config, 'cookie', '')
    called = []
    monkeypatch.setattr(sync_down, 'main', lambda ui: called.append(1) or True)
    sync_down.sync()
    assert called == []


def test_hint_alias_on_suspension(env, monkeypatch, capsys):
    # 封号归档时提示同组替代账号(alias 展示层)
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500}})
    FakeAPI.payloads = [_media_raw(None, 'UserUnavailable')]
    monkeypatch.setattr(sync_down.config, 'alias', {'组': ['u1', 'u2']})
    monkeypatch.setattr(sync_down, 'archive_suspended_user', lambda u, p: None)
    monkeypatch.setattr(sync_down, 'main', lambda ui: True)
    sync_down.sync()
    out = capsys.readouterr().out
    assert '别名组「组」' in out
    assert 'u2' in out


def test_cmd_add_interactive_and_persists(monkeypatch, tmp_path, capsys):
    users = tmp_path / 'users.json'
    users.write_text(json.dumps({'user_lst': ['a'], 'alias': {}}), encoding='utf-8')
    monkeypatch.setattr(sync_down.config, 'users_path', str(users))
    monkeypatch.setattr(sync_down.config, 'users_raw',
                        json.loads(users.read_text(encoding='utf-8')))
    monkeypatch.setattr(sync_down.config, 'user_lst', ['a'])
    sync_down._cmd_add(['n1', 'a', 'n2'])
    out = capsys.readouterr().out
    assert '已加入: n1' in out and '已加入: n2' in out
    # 已持久化,重载后生效
    cfg2 = sync_down.config.__class__('', users_path=str(users))
    assert cfg2.user_list == ['a', 'n1', 'n2']


def test_cmd_remove(tmp_path, capsys):
    users = tmp_path / 'users.json'
    users.write_text(json.dumps({'user_lst': ['a', 'b']}), encoding='utf-8')
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sync_down.config, 'users_path', str(users))
    monkeypatch.setattr(sync_down.config, 'users_raw',
                        json.loads(users.read_text(encoding='utf-8')))
    monkeypatch.setattr(sync_down.config, 'user_lst', ['a', 'b'])
    try:
        sync_down._cmd_remove(['a', 'nope'])
    finally:
        monkeypatch.undo()
    cfg2 = sync_down.config.__class__('', users_path=str(users))
    assert cfg2.user_list == ['b']


def test_cmd_list_shows_state(env, capsys):
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500, 'checked_at': 'x'}})
    sync_down._cmd_list()
    out = capsys.readouterr().out
    assert 'u1' in out and 'latest_media_id=500' in out
    assert '别名组' in out


def test_cmd_dedup_dry_run_then_apply(tmp_path, capsys):
    # 存量去重:dry-run 打印计划;--apply 执行,每组保留最早(same_user + alias_group,cross 不动)
    for user in ('u1', 'u2', 'u3'):
        (tmp_path / user).mkdir()
    (tmp_path / 'u1' / '2024-01-01 00-00-111-img0.jpg').write_bytes(b'same')    # 组内最早(保留)
    (tmp_path / 'u2' / '2026-01-01 00-00-222-img0.jpg').write_bytes(b'same')    # 同组较晚(删)
    (tmp_path / 'u1' / '2025-01-01 00-00-333-img0.jpg').write_bytes(b'cross-x') # 与 u3 跨组
    (tmp_path / 'u3' / '2026-01-01 00-00-444-img0.jpg').write_bytes(b'cross-x') # 跨组(不动)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sync_down.config, 'save_path', str(tmp_path))
    monkeypatch.setattr(sync_down.config, 'alias', {'组': ['u1', 'u2']})
    try:
        sync_down._cmd_dedup(apply=False)
        out = capsys.readouterr().out
        assert '计划删除 1 个重复文件' in out  # 只删 u2 的(组内);跨组不动
        assert (tmp_path / 'u2' / '2026-01-01 00-00-222-img0.jpg').exists()  # dry-run 未执行

        sync_down._cmd_dedup(apply=True)
        out = capsys.readouterr().out
        assert '已删除 1 个' in out
        assert not (tmp_path / 'u2' / '2026-01-01 00-00-222-img0.jpg').exists()
        assert (tmp_path / 'u1' / '2024-01-01 00-00-111-img0.jpg').exists()   # 最早保留
        assert (tmp_path / 'u3' / '2026-01-01 00-00-444-img0.jpg').exists()   # 跨组保留
        assert (tmp_path / 'u1' / '2025-01-01 00-00-333-img0.jpg').exists()   # 跨组保留
    finally:
        monkeypatch.undo()


def test_cmd_dedup_nothing_to_do(tmp_path, capsys):
    (tmp_path / 'u1').mkdir()
    (tmp_path / 'u1' / 'a.jpg').write_bytes(b'only')
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sync_down.config, 'save_path', str(tmp_path))
    monkeypatch.setattr(sync_down.config, 'alias', {})
    try:
        sync_down._cmd_dedup(apply=True)
    finally:
        monkeypatch.undo()
    assert '无待清理' in capsys.readouterr().out


def test_cmd_alias(tmp_path, capsys):
    users = tmp_path / 'users.json'
    users.write_text(json.dumps({'user_lst': [], 'alias': {}}), encoding='utf-8')
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sync_down.config, 'users_path', str(users))
    monkeypatch.setattr(sync_down.config, 'users_raw',
                        json.loads(users.read_text(encoding='utf-8')))
    monkeypatch.setattr(sync_down.config, 'alias', {})
    try:
        sync_down._cmd_alias('组', ['x', ' y '])
    finally:
        monkeypatch.undo()
    cfg2 = sync_down.config.__class__('', users_path=str(users))
    assert cfg2.alias == {'组': ['x', 'y']}


def test_norm_name():
    assert sync_down._norm_name('白崽七七') == '白崽七七'
    assert sync_down._norm_name('白崽七七（攒钱做胸臀胯）') == '白崽七七攒钱做胸臀胯'
    assert sync_down._norm_name('Qlin✨🚱') == 'qlin'
    assert sync_down._norm_name('  A B  ') == 'ab'
    assert sync_down._norm_name(None) == ''


def test_alias_candidates_prefix_match():
    cands = sync_down._alias_candidates([
        ('Baizaiqiqi', '白崽七七'),
        ('fats5447894', '白崽七七（攒钱做胸臀胯）'),
        ('naivrel', '𝐍𝐚𝐢𝐯𝐫𝐞𝐥'),
    ])
    assert ('Baizaiqiqi', 'fats5447894') in [(c[0], c[1]) for c in cands]
    assert len(cands) == 1  # naivrel 不参与


def test_alias_candidates_no_match_for_short_names():
    # 长度 < 2 的归一化昵称不参与,避免噪音
    assert sync_down._alias_candidates([('a', '意'), ('b', '意意喵')]) == []
    assert sync_down._alias_candidates([]) == []


def test_build_dup_report(tmp_path):
    # 构造库:u1 两张图(一张与 u2 重复,一张独立);u2 一张图
    import hashlib
    for user in ('u1', 'u2'):
        (tmp_path / user).mkdir()
    (tmp_path / 'u1' / 'a.jpg').write_bytes(b'content-a')
    (tmp_path / 'u1' / 'b.jpg').write_bytes(b'content-b')
    (tmp_path / 'u2' / 'c.jpg').write_bytes(b'content-a')  # 与 u1/a.jpg 重复
    (tmp_path / 'u1' / 'meta.csv').write_text('x')

    rep = sync_down.build_dup_report(str(tmp_path), {})
    assert rep['total'] == 3 and rep['unique'] == 2 and rep['dup_groups'] == 1
    assert rep['savable_mb'] > 0
    g = rep['groups'][0]
    assert g['scope'] == 'cross'  # 跨用户且无别名组
    assert rep['alias_hits'] == {}


def test_build_dup_report_alias_group_scope(tmp_path):
    # 组内重复 → alias_group;组外用户同内容重复 → cross
    for user in ('u1', 'u2', 'u3'):
        (tmp_path / user).mkdir()
    (tmp_path / 'u1' / 'a.jpg').write_bytes(b'same')   # u1/u2 同组重复
    (tmp_path / 'u2' / 'b.jpg').write_bytes(b'same')
    (tmp_path / 'u3' / 'c.jpg').write_bytes(b'same')   # 与组外 u3 也重复 → 整组跨组
    (tmp_path / 'u3' / 'd.jpg').write_bytes(b'other')  # 唯一内容

    rep = sync_down.build_dup_report(str(tmp_path), {'组': ['u1', 'u2']})
    assert rep['dup_groups'] == 1
    assert rep['groups'][0]['scope'] == 'cross'  # u3 参与使重复跨出组边界
    assert rep['alias_hits'] == {}


def test_build_dup_report_pure_alias_group(tmp_path):
    # 组内两成员互发老图(无组外参与)→ scope=alias_group + 命中计数
    for user in ('u1', 'u2'):
        (tmp_path / user).mkdir()
    (tmp_path / 'u1' / 'a.jpg').write_bytes(b'same')
    (tmp_path / 'u2' / 'b.jpg').write_bytes(b'same')
    (tmp_path / 'u2' / 'c.jpg').write_bytes(b'other')

    rep = sync_down.build_dup_report(str(tmp_path), {'组': ['u1', 'u2']})
    assert rep['groups'][0]['scope'] == 'alias_group'
    assert rep['alias_hits'] == {'组': 1}


def test_cmd_report_prints(tmp_path, capsys):
    (tmp_path / 'u1').mkdir()
    (tmp_path / 'u1' / 'a.jpg').write_bytes(b'x' * 1024)
    (tmp_path / 'u1' / 'a2.jpg').write_bytes(b'x' * 1024)  # 重复
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sync_down.config, 'save_path', str(tmp_path))
    monkeypatch.setattr(sync_down.config, 'alias', {})
    try:
        sync_down._cmd_report()
    finally:
        monkeypatch.undo()
    out = capsys.readouterr().out
    assert '重复组: 1' in out
    assert '可节省空间' in out


def test_sync_prints_alias_candidates(env, monkeypatch, capsys):
    # 换号识别:名单内昵称相似 → sync 启动提示
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500, 'name': '白崽七七'},
                 'u2': {'rest_id': '456', 'latest_media_id': 500, 'name': '白崽七七二号'}})
    monkeypatch.setattr(sync_down.config, 'user_lst', 'u1,u2')
    monkeypatch.setattr(sync_down.config, 'alias', {})
    FakeAPI.payloads = [_media_raw(500), _media_raw(500)]  # 都无变化
    monkeypatch.setattr(sync_down, 'main', lambda ui: True)
    sync_down.sync()
    out = capsys.readouterr().out
    assert '疑似同人/换号' in out
    assert 'u1' in out and 'u2' in out


def test_sync_skips_candidates_for_grouped_users(env, monkeypatch, capsys):
    # 已归组账号不参与候选提示(避免噪音);未归组仍提示
    _state(env, {'u1': {'rest_id': '123', 'latest_media_id': 500, 'name': '白崽七七'},
                 'u2': {'rest_id': '456', 'latest_media_id': 500, 'name': '白崽七七二号'},
                 'u3': {'rest_id': '789', 'latest_media_id': 500, 'name': '新人'}})
    monkeypatch.setattr(sync_down.config, 'user_lst', 'u1,u2,u3')
    monkeypatch.setattr(sync_down.config, 'alias', {'组': ['u1', 'u2']})
    FakeAPI.payloads = [_media_raw(500)] * 3
    monkeypatch.setattr(sync_down, 'main', lambda ui: True)
    sync_down.sync()
    out = capsys.readouterr().out
    assert '别名组「组」' in out
    assert '疑似同人/换号' not in out  # u1/u2 已归组,u3 无相似对象
