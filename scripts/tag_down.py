import asyncio
import re
import os
import sys
import json
from datetime import datetime
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 根目录,以导入 tw_dl/

from tw_dl.utils import del_special_char, stamp2time, get_highest_video_quality, hash_save_token, get_tweet_msecs
from tw_dl.api import TwitterAPI, RateLimitError, AuthError, TwitterAPIError
from tw_dl.csv_writer import CsvWriter
from tw_dl.downloader import download_many
from transaction_generate import get_url_path
from transaction_generate import get_transaction_id


##########配置区域##########

cookie = 'auth_token=xxxxxxxxxxx; ct0=xxxxxxxxxxx;'
# 填入 cookie (auth_token与ct0字段) //重要:替换掉其中的x即可, 注意不要删掉分号

tag = '#ヨルクラ'
# 填入tag 带上#号 可留空
_filter = ""
# (可选项) 高级搜索
# 请在 https://x.com/search-advanced 中组装搜索条件，复制搜索栏的内容填入_filter
# 注意，_filter中所有出现的双引号都需要改为单引号或添加转义符 例如 "Monika" -> 'Monika'

# ↑↑ 当tag选项留空时，将尝试以_filter的内容作为文件夹名称

down_count = 100
# 因为搜索结果数量可能极大，故手动确定下载总量(近似)，填50的倍数，最少50

media_latest = False
# media_latest为True时，对应 [最新] 标签页，False对应 [媒体] 标签页 (与文本模式无关)
# 开启时建议 _filter 设置为 _filter = 'filter:links -filter:replies'

# ------------------------ #

text_down = False
# 开启后变为文本下载模式，会消耗大量API次数
# 开启文本下载时 不要包含 filter:links

##########配置区域##########

max_concurrent_requests = 8     #最大并发数量，默认为8，遇到多次下载失败时适当降低

if text_down:
    entries_count = 20
    product = 'Latest'
    mode = 'text'
else:
    entries_count = 50
    product = 'Media'
    mode = 'media'
    if media_latest:
        entries_count = 20
        product = 'Latest'
        mode = 'media_latest'
_filter = ' ' + _filter


def _is_search_done(media_lst, empty_pages, max_empty_pages=2):
    """搜索页终止判定(原「空页即停」会误停:一页全是纯文本/解析失败就提前结束)。
    - media_lst None:出错或无更多结果(真尽头)→ 立即停
    - 空页(有 moduleItems 但解析不出媒体):连续 max_empty_pages 页才停
    - 正常页:重置计数
    返回 (是否停止, 新计数)"""
    if media_lst is None:
        return True, empty_pages
    if not media_lst:
        return empty_pages + 1 >= max_empty_pages, empty_pages + 1
    return False, 0


class tag_down():
    def __init__(self):
        self.csv = None
        self.api = None

        if tag:
            self.folder_path = os.getcwd() + os.sep + del_special_char(tag) + os.sep
        else:
            self.folder_path = os.getcwd() + os.sep + del_special_char(_filter) + os.sep

        if not os.path.exists(self.folder_path):   #创建文件夹
            os.makedirs(self.folder_path)

        self.csv = CsvWriter(
            self.folder_path,
            f'{datetime.now().strftime("%Y-%m-%d %H-%M-%S")}-{mode}.csv',
            [['Run Time : ' + datetime.now().strftime('%Y-%m-%d %H-%M-%S')]],
            (['Tweet Date', 'Display Name', 'User Name', 'Tweet URL', 'Tweet Content', 'Favorite Count',
              'Retweet Count', 'Reply Count'] if text_down else
             ['Tweet Date', 'Display Name', 'User Name', 'Tweet URL', 'Media Type', 'Media URL', 'Saved Path',
              'Tweet Content', 'Favorite Count', 'Retweet Count', 'Reply Count']),
            stamp_index=0,
        )

        self.api = TwitterAPI(cookie)
        self.api.headers['referer'] = f'https://twitter.com/search?q={quote(tag + _filter)}&src=typed_query&f=media'

        self.cursor = ''

        self.ct = get_transaction_id()

        empty_pages = 0
        try:
            for i in range(down_count // entries_count):
                url = 'https://x.com/i/api/graphql/AIdc203rPpK_k_2KWSdm7g/SearchTimeline?variables={"rawQuery":"' + quote(tag + _filter) + '","count":' + str(entries_count) + ',"cursor":"' + self.cursor + '","querySource":"typed_query","product":"' + product + '"}&features={"rweb_video_screen_enabled":false,"profile_label_improvements_pcf_label_in_post_enabled":true,"rweb_tipjar_consumption_enabled":true,"verified_phone_label_enabled":false,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_timeline_navigation_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"premium_content_api_read_enabled":false,"communities_web_enable_tweet_community_results_fetch":true,"c9s_tweet_anatomy_moderator_badge_enabled":true,"responsive_web_grok_analyze_button_fetch_trends_enabled":false,"responsive_web_grok_analyze_post_followups_enabled":true,"responsive_web_jetfuel_frame":false,"responsive_web_grok_share_attachment_enabled":true,"articles_preview_enabled":true,"responsive_web_edit_tweet_api_enabled":true,"graphql_is_translatable_rweb_tweet_is_translatable_enabled":true,"view_counts_everywhere_api_enabled":true,"longform_notetweets_consumption_enabled":true,"responsive_web_twitter_article_tweet_consumption_enabled":true,"tweet_awards_web_tipping_enabled":false,"responsive_web_grok_show_grok_translated_post":false,"responsive_web_grok_analysis_button_from_backend":false,"creator_subscriptions_quote_tweet_preview_enabled":false,"freedom_of_speech_not_reach_fetch_enabled":true,"standardized_nudges_misinfo":true,"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":true,"longform_notetweets_rich_text_read_enabled":true,"longform_notetweets_inline_media_enabled":true,"responsive_web_grok_image_annotation_enabled":true,"responsive_web_enhance_cards_enabled":false}'
                _path = get_url_path(url)
                url = url.replace('{', '%7B').replace('}', '%7D')
                self.api.headers['x-client-transaction-id'] = self.ct.generate_transaction_id(method='GET', path=_path)
                if text_down:
                    if not self.search_save_text(url):
                        break
                else:
                    if media_latest:
                        media_lst = self.search_media_latest(url)
                    else:
                        media_lst = self.search_media(url)
                    stop, empty_pages = _is_search_done(media_lst, empty_pages)
                    if stop:
                        break   #出错/无更多结果,或连续多页无媒体可解析
                    jobs = []
                    for m in media_lst:
                        media_url, csv_info, is_image = m
                        if is_image:
                            media_url += '?format=png&name=4096x4096'
                        jobs.append((media_url, csv_info[6], False, csv_info))  #0:url 1:filename 2:fallback 3:csv_info
                    asyncio.run(download_many(self.api, jobs, max_concurrent_requests, post_hook=self._csv_hook))
        finally:
            if self.csv:
                self.csv.close()
            if self.api:
                self.api.close()

    def _csv_hook(self, url, filename, extra):
        self.csv.write(extra)

    def search_media(self, url):
        #接收某页链接，返回该页所有图片地址
        media_lst = []

        try:
            raw_data = self.api.get_json(url)
        except RateLimitError:
            print('API次数已超限')
            return None
        except (AuthError, TwitterAPIError) as e:
            print('获取数据失败')
            print(e)
            return None
        if not self.cursor: #第一次
            raw_data = raw_data['data']['search_by_raw_query']['search_timeline']['timeline']['instructions'][-1]['entries']
            if len(raw_data) == 2:
                return None
            self.cursor = raw_data[-1]['content']['value']
            raw_data_lst = raw_data[0]['content']['items']
        else:
            raw_data = raw_data['data']['search_by_raw_query']['search_timeline']['timeline']['instructions']
            self.cursor = raw_data[-1]['entry']['content']['value']
            if 'moduleItems' in raw_data[0]:
                raw_data_lst = raw_data[0]['moduleItems']
            else:
                return None

        for tweet in raw_data_lst:
            tweet = tweet['item']['itemContent']['tweet_results']['result']
            try:
                display_name = tweet['core']['user_results']['result']['legacy']['name']
                screen_name = '@' + tweet['core']['user_results']['result']['legacy']['screen_name']
            except Exception:   #低概率事件
                continue
            time_stamp = get_tweet_msecs(tweet)
            if time_stamp is None:
                continue
            try:
                Favorite_Count = tweet['legacy']['favorite_count']
                Retweet_Count = tweet['legacy']['retweet_count']
                Reply_Count = tweet['legacy']['reply_count']
                _status_id = tweet['rest_id']
                tweet_url = f'https://twitter.com/{screen_name}/status/{_status_id}'
                __text_content = tweet['legacy']['full_text']
                tweet_content = re.sub(r'https?://t\.co/\w+\s*$', '', __text_content).strip()
            except Exception as e:
                print(e)
                continue
            try:
                raw_media_lst = tweet['legacy']['extended_entities']['media']
                for _media in raw_media_lst:
                    if 'video_info' in _media:
                        media_url = get_highest_video_quality(_media['video_info']['variants'])
                        media_type = 'Video'
                        is_image = False
                        _file_name = f'{self.folder_path}{stamp2time(time_stamp)}_{screen_name}_{hash_save_token(media_url)}.mp4'
                    else:
                        media_url = _media['media_url_https']
                        media_type = 'Image'
                        is_image = True
                        _file_name = f'{self.folder_path}{stamp2time(time_stamp)}_{screen_name}_{hash_save_token(media_url)}.png'

                    media_csv_info = [time_stamp, display_name, screen_name, tweet_url, media_type, media_url, _file_name, tweet_content, Favorite_Count, Retweet_Count, Reply_Count]
                    media_lst.append([media_url, media_csv_info, is_image])
            except Exception as e:
                print(e)
                continue
        return media_lst

    def search_media_latest(self, url):
        media_lst = []

        try:
            raw_data = self.api.get_json(url)
        except RateLimitError:
            print('API次数已超限')
            return None
        except (AuthError, TwitterAPIError) as e:
            print('获取数据失败')
            print(e)
            return None
        if not self.cursor: #第一次
            raw_data = raw_data['data']['search_by_raw_query']['search_timeline']['timeline']['instructions'][-1]['entries']
            if len(raw_data) == 2:
                return None
            self.cursor = raw_data[-1]['content']['value']
            raw_data_lst = raw_data[:-2]
        else:
            raw_data = raw_data['data']['search_by_raw_query']['search_timeline']['timeline']['instructions']
            self.cursor = raw_data[-1]['entry']['content']['value']
            if 'entries' in raw_data[0]:
                raw_data_lst = raw_data[0]['entries']
            else:
                return None

        for tweet in raw_data_lst:
            if 'promoted' in tweet['entryId']:
                continue
            tweet = tweet['content']['itemContent']['tweet_results']['result']
            try:
                display_name = tweet['core']['user_results']['result']['legacy']['name']
                screen_name = '@' + tweet['core']['user_results']['result']['legacy']['screen_name']
            except Exception:   #低概率事件
                continue
            time_stamp = get_tweet_msecs(tweet)
            if time_stamp is None:
                continue
            try:
                Favorite_Count = tweet['legacy']['favorite_count']
                Retweet_Count = tweet['legacy']['retweet_count']
                Reply_Count = tweet['legacy']['reply_count']
                _status_id = tweet['rest_id']
                tweet_url = f'https://twitter.com/{screen_name}/status/{_status_id}'
                __text_content = tweet['legacy']['full_text']
                tweet_content = re.sub(r'https?://t\.co/\w+\s*$', '', __text_content).strip()
            except Exception as e:
                print(e)
                continue
            try:
                raw_media_lst = tweet['legacy']['extended_entities']['media']
                for _media in raw_media_lst:
                    if 'video_info' in _media:
                        media_url = get_highest_video_quality(_media['video_info']['variants'])
                        media_type = 'Video'
                        is_image = False
                        _file_name = f'{self.folder_path}{stamp2time(time_stamp)}_{screen_name}_{hash_save_token(media_url)}.mp4'
                    else:
                        media_url = _media['media_url_https']
                        media_type = 'Image'
                        is_image = True
                        _file_name = f'{self.folder_path}{stamp2time(time_stamp)}_{screen_name}_{hash_save_token(media_url)}.png'
                    media_csv_info = [time_stamp, display_name, screen_name, tweet_url, media_type, media_url, _file_name, tweet_content, Favorite_Count, Retweet_Count, Reply_Count]
                    media_lst.append([media_url, media_csv_info, is_image])

            except KeyError:
                # 仍存在部分纯文本推文无法排除
                pass
            except Exception as e:
                print(e)

        return media_lst

    def search_save_text(self, url):
        #接收某页链接，保存所有文本内容

        try:
            raw_data = self.api.get_json(url)
        except RateLimitError:
            print('API次数已超限')
            return False
        except (AuthError, TwitterAPIError) as e:
            print('获取数据失败')
            print(e)
            return False
        if not self.cursor: #第一次
            raw_data = raw_data['data']['search_by_raw_query']['search_timeline']['timeline']['instructions'][-1]['entries']
            if len(raw_data) == 2:
                return False
            self.cursor = raw_data[-1]['content']['value']
            raw_data_lst = raw_data[:-2]
        else:
            raw_data = raw_data['data']['search_by_raw_query']['search_timeline']['timeline']['instructions']
            self.cursor = raw_data[-1]['entry']['content']['value']
            if len(raw_data) == 2:
                return False
            raw_data_lst = raw_data[0]['entries']

        for tweet in raw_data_lst:
            if 'promoted' in tweet['entryId']:
                continue
            tweet = tweet['content']['itemContent']['tweet_results']['result']
            if 'tweet' in tweet and 'edit_control' in tweet['tweet']:
                tweet = tweet['tweet']
            time_stamp = get_tweet_msecs(tweet)
            if time_stamp is None:
                continue
            try:
                display_name = tweet['core']['user_results']['result']['legacy']['name']
                screen_name = '@' + tweet['core']['user_results']['result']['legacy']['screen_name']
            except Exception:   #低概率事件
                continue

            try:
                Favorite_Count = tweet['legacy']['favorite_count']
                Retweet_Count = tweet['legacy']['retweet_count']
                Reply_Count = tweet['legacy']['reply_count']
                _status_id = tweet['rest_id']
                tweet_url = f'https://twitter.com/{screen_name}/status/{_status_id}'
                __text_content = tweet['legacy']['full_text']
                tweet_content = re.sub(r'https?://t\.co/\w+\s*$', '', __text_content).strip()
            except Exception as e:
                print(e)
                continue

            self.csv.write([time_stamp, display_name, screen_name, tweet_url, tweet_content, Favorite_Count, Retweet_Count, Reply_Count])
        return True


if __name__ == '__main__':
    print('无过程输出...(๑´ڡ`๑)')
    tag_down()
    print('已完成')
