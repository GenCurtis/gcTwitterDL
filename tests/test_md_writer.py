# -*- coding: utf-8 -*-
# MdWriter:推文分组、日期标题、视频标签、分卷、转推注释
import glob
import os

from tw_dl.md_writer import MdWriter

TS = 1700000000000  # 2023-11-15


def _info(tweet_id, media_type='Image', filename='2023-11-15 06-13-img_0.jpg',
          prefix='2023-11-15 06-13-img', text='hello world'):
    return [TS, 'Display', '@user', f'https://x.com/user/status/{tweet_id}', media_type,
            'https://pbs.twimg.com/media/a.jpg', filename, text, '1', '2', '3']


def _read(path):
    with open(path, encoding='utf-8-sig') as f:
        return f.read()


def test_grouping_by_tweet(tmp_path):
    w = MdWriter(str(tmp_path), 'User', 'screen', '', False, 0)
    info = _info(123)
    w.media_tweet_input(info, '2023-11-15 06-13-img')
    w.media_tweet_input(info, '2023-11-15 06-13-img')  # 同一推文第二张图
    w.md_close()

    content = _read(glob.glob(str(tmp_path / '*.md'))[0])
    assert '## 2023-11' in content          # 年月标题
    assert content.count('hello world') == 1  # 推文内容只出现一次
    assert content.count('![](') == 2         # 两张图
    assert '1 Likes, 2 Retweets, 3 Replies' in content
    assert 'status/123' in content


def test_video_tag_and_space_escape(tmp_path):
    w = MdWriter(str(tmp_path), 'User', 'screen', '', False, 0)
    w.media_tweet_input(_info(124, media_type='Video', filename='2023-11-15 06-13-vid_0.mp4',
                              prefix='2023-11-15 06-13-vid'), '2023-11-15 06-13-vid')
    w.md_close()
    content = _read(glob.glob(str(tmp_path / '*.md'))[0])
    assert '<video src="2023-11-15%2006-13-vid_0.mp4" controls></video>' in content
    assert '![](' not in content


def test_media_count_limit_splits_files(tmp_path):
    w = MdWriter(str(tmp_path), 'User', 'screen', '', False, 1)  # 每文件 1 媒体
    w.media_tweet_input(_info(125), '2023-11-15 06-13-img')
    w.media_tweet_input(_info(126, filename='2023-11-15 06-13-img_1.jpg'), '2023-11-15 06-13-img')
    w.md_close()

    files = sorted(glob.glob(str(tmp_path / '*.md')))
    assert len(files) == 2
    c1, c2 = _read(files[0]), _read(files[1])
    assert c1.count('![](') == 1 and c2.count('![](') == 1
    assert 'status/125' in c1 and 'status/126' in c2


def test_retweet_prefix_annotation(tmp_path):
    w = MdWriter(str(tmp_path), 'User', 'screen', '', False, 0)
    w.media_tweet_input(_info(127), '2023-11-15 06-13-img-retweet')
    w.md_close()
    content = _read(glob.glob(str(tmp_path / '*.md'))[0])
    assert '*User retweeted*' in content


def test_likes_mode_skips_date_heading(tmp_path):
    w = MdWriter(str(tmp_path), 'User', 'screen', '', True, 0)
    w.media_tweet_input(_info(128), '2023-11-15 06-13-img')
    w.md_close()
    content = _read(glob.glob(str(tmp_path / '*.md'))[0])
    assert '## 2023-11' not in content


def test_concurrent_writes_rows_intact(tmp_path):
    # R7 烟雾测试:多线程并发写入(模拟 download_many 的 pre_hook 并发)不应抛错/丢行
    import threading
    w = MdWriter(str(tmp_path), 'User', 'screen', '', False, 0)
    errors = []

    def writer(n):
        try:
            for i in range(5):
                w.media_tweet_input(
                    _info(1000 + n * 10 + i, filename=f'2023-11-15 06-13-img{n}_{i}.jpg'),
                    f'2023-11-15 06-13-img{n}_{i}')
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    w.md_close()

    assert not errors
    content = _read(glob.glob(str(tmp_path / '*.md'))[0])
    assert content.count('![](') == 50   # 50 条媒体记录全部完整
    assert content.count('status/') == 50
