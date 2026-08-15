# -*- coding: utf-8 -*-
import os

from tw_dl.archive import archive_suspended_user, SUSPENDED_PREFIX, is_archived


def _make_user_dir(tmp_path, name='yuozi_my'):
    d = tmp_path / name
    d.mkdir()
    (d / '1.jpg').write_bytes(b'img')
    (d / '2024-01-01.csv').write_text('a,b')
    (d / 'cache_data.log').write_bytes(b'\x80pickle')
    (d / 'notes.md').write_text('# content')
    return d


def test_archive_renames_and_cleans(tmp_path):
    user_dir = _make_user_dir(tmp_path)
    assert archive_suspended_user('yuozi_my', str(tmp_path)) is True

    archived = tmp_path / f'{SUSPENDED_PREFIX}yuozi_my'
    assert archived.is_dir()
    assert (archived / '1.jpg').exists()          # 媒体保留
    assert not (archived / '2024-01-01.csv').exists()   # csv 清理
    assert not (archived / 'cache_data.log').exists()   # 缓存清理
    assert (archived / 'notes.md').exists()       # md 保留
    assert not user_dir.exists()


def test_archive_idempotent(tmp_path):
    _make_user_dir(tmp_path)
    assert archive_suspended_user('yuozi_my', str(tmp_path)) is True
    assert archive_suspended_user('yuozi_my', str(tmp_path)) is False  # 原目录已不存在
    assert archive_suspended_user(f'{SUSPENDED_PREFIX}yuozi_my', str(tmp_path)) is False  # 已归档


def test_archive_missing_dir(tmp_path):
    assert archive_suspended_user('nobody', str(tmp_path)) is False


def test_is_archived():
    assert is_archived('yuozi_my') is False
    assert is_archived(f'{SUSPENDED_PREFIX}yuozi_my') is True


def test_archive_target_collision(tmp_path):
    # 目标已存在(上次归档残留)→ 追加时间戳,不覆盖
    _make_user_dir(tmp_path)
    archived = tmp_path / f'{SUSPENDED_PREFIX}yuozi_my'
    archived.mkdir()
    (archived / 'keep.jpg').write_bytes(b'x')

    assert archive_suspended_user('yuozi_my', str(tmp_path)) is True
    entries = [e for e in os.listdir(str(tmp_path)) if e.startswith(SUSPENDED_PREFIX)]
    assert len(entries) == 2
    assert (archived / 'keep.jpg').exists()  # 原归档未被覆盖
