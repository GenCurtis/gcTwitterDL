# -*- coding: utf-8 -*-
# Markdown 输出(原 md_gen.py,逻辑原样保留:按推文分组、日期标题、媒体数量分卷)
import re
import threading
from datetime import datetime

from .utils import stamp2time


class MdWriter:
    def __init__(self, save_path, user_name, screen_name, tweet_range, has_likes, media_count_limit):
        self.f = open(f'{save_path}/{screen_name}-{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}_1.md', 'w', encoding='utf-8-sig', newline='')
        self.f.write(f"{user_name} {screen_name}\n")
        self.f.write(f"Tweet Range: {tweet_range}\n")
        self.f.write(f"Save Path: {save_path}\n")

        self.save_path = save_path
        self.user_name = user_name
        self.screen_name = screen_name
        self.tweet_range = tweet_range
        self.has_likes = has_likes

        self.media_count_limit = media_count_limit  # 单个 Markdown 最大媒体数量,0 = 不限制
        self.current_tweet_info = ['', '', '']  # 0-当前推文 status id, 1-互动数据文本, 2-年月日期(不含转推/likes)
        self.file_media_count = 0  # 当前文件媒体数量
        self.file_count = 1  # 已输出文件数量
        self._lock = threading.Lock()  # pre_hook 多线程并发调用,保证输出不交错

    def md_close(self):
        with self._lock:
            self.f.write('\n' + self.current_tweet_info[1] + '\n')  # 输出最后一个推文的互动数据
            self.f.close()

    def media_tweet_input(self, csv_info, prefix):
        with self._lock:
            fixed_filename = csv_info[6].replace(' ', '%20')
            fixed_timestr = csv_info[0] if type(csv_info[0]) == str else stamp2time(csv_info[0])
            currentDate = fixed_timestr[0:7]

            tweet_status_id = re.findall(r"status/(\d+)", csv_info[3])[0]

            if self.current_tweet_info[0] != tweet_status_id:  # 新推文
                self.f.write(f'\n{self.current_tweet_info[1]}\n\n' if len(self.current_tweet_info[1]) > 0 else '')  # 上一个推文的互动数据

                if self.media_count_limit > 0 and self.file_media_count >= self.media_count_limit:  # 超出媒体限制,新建文件
                    self.f.close()
                    self.file_media_count = 0
                    self.file_count += 1
                    if self.has_likes:
                        new_filename = f'{self.save_path}/{self.screen_name}-{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}_{self.file_count}.md'
                    elif 'retweet' in prefix:
                        new_filename = f'{self.save_path}/{self.screen_name}-{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}_{self.file_count}_{self.current_tweet_info[2]}.md'
                    else:
                        new_filename = f'{self.save_path}/{self.screen_name}-{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}_{self.file_count}_{currentDate}.md'
                    self.f = open(new_filename, 'w', encoding='utf-8-sig', newline='')
                    self.f.write(f"{self.user_name} {self.screen_name}\n")
                    self.f.write(f"Tweet Range: {self.tweet_range}\n")
                    self.f.write(f"Save Path: {self.save_path}\n\n")

                if not self.has_likes and 'retweet' not in prefix and currentDate != self.current_tweet_info[2]:
                    self.f.write(f'## {currentDate}\n')  # 年月标题
                    self.current_tweet_info[2] = currentDate

                prefix_retweet = f'*{self.user_name} retweeted*\n' if 'retweet' in prefix else ''  # 转推注释
                self.f.write(f'{prefix_retweet}{csv_info[1]} {csv_info[2]} · {fixed_timestr} [src]({csv_info[3]})\n')
                self.f.write(csv_info[7] + '\n')
                self.current_tweet_info[0] = tweet_status_id
                self.current_tweet_info[1] = f'{csv_info[8]} Likes, {csv_info[9]} Retweets, {csv_info[10]} Replies'

            self.f.write(f'<video src="{fixed_filename}" controls></video>' if 'Video' in csv_info[4] else f'[![]({fixed_filename})]({csv_info[5]})')
            self.file_media_count += 1
