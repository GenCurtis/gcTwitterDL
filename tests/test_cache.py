# -*- coding: utf-8 -*-
import os

from tw_dl.cache import DownloadCache


def test_mark_dedupe(tmp_path):
    cache = DownloadCache(str(tmp_path))
    assert cache.is_downloaded('http://x/1.jpg') is False  # 未下载过
    cache.mark('http://x/1.jpg')                            # 成功后才登记
    assert cache.is_downloaded('http://x/1.jpg') is True
    assert cache.is_downloaded('http://x/2.jpg') is False


def test_persists_across_instances(tmp_path):
    cache = DownloadCache(str(tmp_path))
    cache.mark('http://x/1.jpg')

    cache2 = DownloadCache(str(tmp_path))  # 重新加载
    assert cache2.is_downloaded('http://x/1.jpg') is True
    assert cache2.is_downloaded('http://x/2.jpg') is False


def test_failed_download_not_marked(tmp_path):
    # 失败的文件不 mark → 下次运行仍会重试(数据不丢)
    cache = DownloadCache(str(tmp_path))
    assert cache.is_downloaded('http://x/1.jpg') is False
    cache2 = DownloadCache(str(tmp_path))
    assert cache2.is_downloaded('http://x/1.jpg') is False


def test_atomic_write_no_tmp_left(tmp_path):
    cache = DownloadCache(str(tmp_path))
    cache.mark('http://x/1.jpg')
    assert os.path.exists(os.path.join(str(tmp_path), 'cache_data.log'))
    assert not os.path.exists(os.path.join(str(tmp_path), 'cache_data.log.tmp'))


def test_corrupt_cache_recovers(tmp_path):
    cache_path = os.path.join(str(tmp_path), 'cache_data.log')
    with open(cache_path, 'wb') as f:
        f.write(b'not a pickle')
    cache = DownloadCache(str(tmp_path))  # 不崩溃,重建
    cache.mark('http://x/1.jpg')
    assert cache.is_downloaded('http://x/1.jpg') is True
