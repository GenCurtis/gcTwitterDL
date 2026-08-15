# -*- coding: utf-8 -*-
# 内容级去重(DedupIndex):范围(同用户/同组)、保留最早、跨组不删、索引持久化/容错
import json
import os

from tw_dl.dedup import DedupIndex


def _make(root, user, name, content):
    d = os.path.join(root, user)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), 'wb') as f:
        f.write(content)
    return os.path.join(d, name)


def test_no_match_keeps_and_registers(tmp_path):
    idx = DedupIndex(str(tmp_path), {}, 'u1')
    assert idx.decide('md5a', os.path.join(str(tmp_path), 'u1', '2024-01-01 00-00-111-img0.jpg')) == 'keep'
    assert idx.index['md5a'] == [{'user': 'u1', 'file': '2024-01-01 00-00-111-img0.jpg'}]


def test_same_user_newer_dropped(tmp_path):
    # 同用户重发:新文件较晚 → drop,不落盘
    idx = DedupIndex(str(tmp_path), {}, 'u1')
    idx.index['md5a'] = [{'user': 'u1', 'file': '2024-01-01 00-00-111-img0.jpg'}]
    assert idx.decide('md5a', os.path.join(str(tmp_path), 'u1', '2026-01-01 00-00-222-img0.jpg')) == 'drop'


def test_same_user_newer_kept_and_removes_old(tmp_path):
    # 新下载的反而更早(如全量乱序):保留新文件,删除库内较晚副本
    old = _make(tmp_path, 'u1', '2026-01-01 00-00-222-img0.jpg', b'x')
    idx = DedupIndex(str(tmp_path), {}, 'u1')
    idx.index['md5a'] = [{'user': 'u1', 'file': '2026-01-01 00-00-222-img0.jpg'}]
    assert idx.decide('md5a', os.path.join(str(tmp_path), 'u1', '2024-01-01 00-00-111-img0.jpg')) == 'keep'
    assert not os.path.exists(old)  # 库内较晚副本被删
    assert idx.index['md5a'] == [{'user': 'u1', 'file': '2024-01-01 00-00-111-img0.jpg'}]


def test_alias_group_members_dedup(tmp_path):
    # 同组小号重发大号老图 → drop
    idx = DedupIndex(str(tmp_path), {'组': ['u1', 'u2']}, 'u2')
    idx.index['md5a'] = [{'user': 'u1', 'file': '2024-01-01 00-00-111-img0.jpg'}]
    assert idx.decide('md5a', os.path.join(str(tmp_path), 'u2', '2026-01-01 00-00-222-img0.jpg')) == 'drop'


def test_cross_user_kept(tmp_path):
    # 跨组(不同人巧合同图)→ 不删,双方都保留
    idx = DedupIndex(str(tmp_path), {'组': ['u1', 'u2']}, 'u3')
    idx.index['md5a'] = [{'user': 'u1', 'file': '2024-01-01 00-00-111-img0.jpg'}]
    assert idx.decide('md5a', os.path.join(str(tmp_path), 'u3', '2026-01-01 00-00-222-img0.jpg')) == 'keep'
    assert len(idx.index['md5a']) == 2  # 双方都登记


def test_index_persists_across_instances(tmp_path):
    idx = DedupIndex(str(tmp_path), {}, 'u1')
    idx.decide('md5a', os.path.join(str(tmp_path), 'u1', '2024-01-01 00-00-111-img0.jpg'))
    idx2 = DedupIndex(str(tmp_path), {}, 'u1')
    assert 'md5a' in idx2.index
    assert not os.path.exists(os.path.join(str(tmp_path), '_dedup_index.json.tmp'))


def test_corrupt_index_recovers(tmp_path):
    with open(os.path.join(str(tmp_path), '_dedup_index.json'), 'w') as f:
        f.write('not json')
    idx = DedupIndex(str(tmp_path), {}, 'u1')
    assert idx.decide('md5a', os.path.join(str(tmp_path), 'u1', '2024-01-01 00-00-111-img0.jpg')) == 'keep'


def test_builds_index_from_existing_library(tmp_path):
    # 首次使用:存量文件自动登记(否则增量下载判定不到旧文件)
    for user in ('u1', 'u2'):
        os.makedirs(os.path.join(str(tmp_path), user), exist_ok=True)
    with open(os.path.join(str(tmp_path), 'u1', '2024-01-01 00-00-111-img0.jpg'), 'wb') as f:
        f.write(b'same')
    with open(os.path.join(str(tmp_path), 'u2', '2025-01-01 00-00-222-img0.jpg'), 'wb') as f:
        f.write(b'same')
    with open(os.path.join(str(tmp_path), 'u1', '2024-01-01 00-00-111.csv'), 'w') as f:
        f.write('x')  # csv 不登记

    idx = DedupIndex(str(tmp_path), {}, 'u1')
    assert len(idx.index) == 1  # 只有 'same' 内容
    assert len(idx.index[next(iter(idx.index))]) == 2  # u1 + u2 两条
    # 索引已持久化,二次实例不重建
    idx2 = DedupIndex(str(tmp_path), {}, 'u1')
    assert idx2.index == idx.index
