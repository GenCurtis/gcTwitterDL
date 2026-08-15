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
from transaction_generate import get_transaction_id
from transaction_generate import get_url_path

##########配置区域##########

cookie = 'auth_token=xxxxxxxxxxx; ct0=xxxxxxxxxxx;'
# 填入 cookie (auth_token与ct0字段) //重要:替换掉其中的x即可, 注意不要删掉分号

target_user = [
    'https://x.com/matchach/status/1855589540905590962',
    '@lilmonix3',
    'https://x.com/yorukura_anime/status/1895307947950924182'
]
# 填入目标用户或指定推文链接, 支持混合与批量, 如上述例子.
# 当目标为单个推文时, 在根目录下生成以推文ID为名的文件夹.
# 当目标为用户时, 在根目录下生成用户名文件夹.

# csv文件命名格式: ./{Tweet_ID or User_Name}/{datetime.now}-Reply.csv
# 媒体文件命名格式: ./{Tweet_ID or User_Name}/{reply_date}_{replier_user_name}_{md5(media_url)[:4]}_reply.{mp4/png}


time_range = "2024-02-06:2024-08-06"
# 限定时间范围, 指定用户时生效, 格式如2023-02-01:2024-05-06, 不填留空则默认无限制.

media_down = True
# 开启后将同时下载评论内容中的媒体文件.

# ------------------------ #


##########高级配置区域##########
# 如无特殊需要 请勿修改

max_concurrent_requests = 8
# 最大并发数量, 默认为8, 对网络有自信的可以调高; 遇到多次下载失败时适当降低.

min_replies = 1
# 筛选最小回复数, 只获取大于该数值的推文的评论区.

min_faves = 0
# 筛选最小喜欢数, 同上.

min_retweets = 0
# 筛选最小转推数, 同上.

search_advanced = ''
# 即tag_down中的高级搜索
# 当填写此项时, 所有配置都将失效, 包括target_user, 下载的内容以该组合获取到的内容为准.
# 使用时建议在组合中限定时间范围, 以防API调用次数超限.
# 自定义组装地址: https://x.com/search-advanced

# ------------------------ #


class Reply_down():
    def __init__(self, _target):
        self.target = _target
        self.folder_path = os.getcwd() + os.sep

        self.api = None
        self.csv = None

        try:
            self.api = TwitterAPI(cookie)

            self.cursor = ''

            self.ct = get_transaction_id()

            if self.get_querystring():  #指定用户
                self.folder_path = os.getcwd() + os.sep + del_special_char(self.user_name) + os.sep
                if not os.path.exists(self.folder_path):   #创建文件夹
                    os.makedirs(self.folder_path)
                self.csv = CsvWriter(
                    self.folder_path,
                    f'{datetime.now().strftime("%Y-%m-%d %H-%M-%S")}-Reply.csv',
                    [['Run Time : ' + datetime.now().strftime('%Y-%m-%d %H-%M-%S')]],
                    ['Parent Tweet URL', 'Replier Display Name', 'Replier User Name', 'Reply Date', 'Reply Content', 'Reply URL',
                     'Reply Favorite Count', 'Reply Retweet Count', 'Reply Reply Count'],
                    stamp_index=3,
                )
                self.get_result()

            else:   #指定推文
                self.folder_path = os.getcwd() + os.sep + del_special_char(self.tweet_id) + os.sep
                if not os.path.exists(self.folder_path):   #创建文件夹
                    os.makedirs(self.folder_path)
                self.csv = CsvWriter(
                    self.folder_path,
                    f'{datetime.now().strftime("%Y-%m-%d %H-%M-%S")}-Reply.csv',
                    [['Run Time : ' + datetime.now().strftime('%Y-%m-%d %H-%M-%S')]],
                    ['Parent Tweet URL', 'Replier Display Name', 'Replier User Name', 'Reply Date', 'Reply Content', 'Reply URL',
                     'Reply Favorite Count', 'Reply Retweet Count', 'Reply Reply Count'],
                    stamp_index=3,
                )
                self.id2reply(self.tweet_id, self.user_name)
        finally:
            if self.csv:
                self.csv.close()
            if self.api:
                self.api.close()

    def id2reply(self, tweet_id: str, parent_user: str):
        _cursor = ''
        is_completed = False
        while not is_completed:
            media_lst = []  # 每页收集一次媒体,整页统一下载(原实现不重置导致重复下载)
            url = 'https://x.com/i/api/graphql/_8aYOgEDz35BrBcBal1-_w/TweetDetail?variables={"focalTweetId":"' + tweet_id + '","cursor":"' + _cursor + '","referrer":"tweet","with_rux_injections":false,"rankingMode":"Relevance","includePromotedContent":false,"withCommunity":true,"withQuickPromoteEligibilityTweetFields":true,"withBirdwatchNotes":true,"withVoice":true}&features={"rweb_video_screen_enabled":false,"profile_label_improvements_pcf_label_in_post_enabled":true,"rweb_tipjar_consumption_enabled":true,"verified_phone_label_enabled":false,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_timeline_navigation_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"premium_content_api_read_enabled":false,"communities_web_enable_tweet_community_results_fetch":true,"c9s_tweet_anatomy_moderator_badge_enabled":true,"responsive_web_grok_analyze_button_fetch_trends_enabled":false,"responsive_web_grok_analyze_post_followups_enabled":true,"responsive_web_jetfuel_frame":false,"responsive_web_grok_share_attachment_enabled":true,"articles_preview_enabled":true,"responsive_web_edit_tweet_api_enabled":true,"graphql_is_translatable_rweb_tweet_is_translatable_enabled":true,"view_counts_everywhere_api_enabled":true,"longform_notetweets_consumption_enabled":true,"responsive_web_twitter_article_tweet_consumption_enabled":true,"tweet_awards_web_tipping_enabled":false,"responsive_web_grok_show_grok_translated_post":false,"responsive_web_grok_analysis_button_from_backend":false,"creator_subscriptions_quote_tweet_preview_enabled":false,"freedom_of_speech_not_reach_fetch_enabled":true,"standardized_nudges_misinfo":true,"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":true,"longform_notetweets_rich_text_read_enabled":true,"longform_notetweets_inline_media_enabled":true,"responsive_web_grok_image_annotation_enabled":true,"responsive_web_enhance_cards_enabled":false}&fieldToggles={"withArticleRichContentState":true,"withArticlePlainText":false,"withGrokAnalyze":false,"withDisallowedReplyControls":false}'
            _path = get_url_path(url)
            url = url.replace('{', '%7B').replace('}', '%7D')
            self.api.headers['x-client-transaction-id'] = self.ct.generate_transaction_id(method='GET', path=_path)
            try:
                raw_data = self.api.get_json(url)
            except RateLimitError:
                print('API次数已超限')
                return
            except (AuthError, TwitterAPIError) as e:
                print('获取数据失败')
                print(e)
                return

            raw_data_backup = raw_data
            if not _cursor: #第一页第一条默认为父推文
                raw_data = raw_data['data']['threaded_conversation_with_injections_v2']['instructions'][1]['entries']
                if len(raw_data) == 2:
                    return
                raw_data.pop(0)
            else:
                raw_data = raw_data['data']['threaded_conversation_with_injections_v2']['instructions'][0]['entries']

            if 'direction' in raw_data_backup['data']['threaded_conversation_with_injections_v2']['instructions'][-1] and raw_data_backup['data']['threaded_conversation_with_injections_v2']['instructions'][-1]['direction'] == 'Bottom':
                is_completed = True
            else:
                _cursor = raw_data[-1]['content']['value']

            for _reply in raw_data:
                try:
                    if 'conversationthread' in _reply['entryId']:
                        if not _reply['content']['items']:
                            continue
                        _reply = _reply['content']['items'][0]
                        if 'conversationthread' not in _reply['entryId']:
                            continue
                        _reply = _reply['item']['itemContent']['tweet_results']['result']
                        if 'tweet' in _reply and 'edit_control' not in _reply:
                            _reply = _reply['tweet']

                        time_stamp = get_tweet_msecs(_reply)
                        if time_stamp is None:
                            continue

                        parent_tweet_url = f'https://x.com/{parent_user}/status/{tweet_id}'
                        replier_display_name = _reply['core']['user_results']['result']['legacy']['name']
                        replier_user_name = '@' + _reply['core']['user_results']['result']['legacy']['screen_name']
                        reply_date = time_stamp
                        reply_content = _reply['legacy']['full_text']
                        reply_url = f'https://x.com/{replier_user_name}/status/{_reply["legacy"]["id_str"]}'
                        reply_favorite_count = _reply['legacy']['favorite_count']
                        reply_retweet_count = _reply['legacy']['retweet_count']
                        reply_reply_count = _reply['legacy']['reply_count']
                    else:
                        continue

                except Exception as e:
                    print(e)
                    continue

                if media_down and 'extended_entities' in _reply['legacy']:
                    try:
                        raw_media_lst = _reply['legacy']['extended_entities']['media']
                        for _media in raw_media_lst:
                            if 'video_info' in _media:
                                media_url = get_highest_video_quality(_media['video_info']['variants'])
                                is_image = False
                                _file_name = f'{self.folder_path}{stamp2time(time_stamp)}_{replier_user_name}_{hash_save_token(media_url)}_reply.mp4'
                            else:
                                media_url = _media['media_url_https']
                                is_image = True
                                _file_name = f'{self.folder_path}{stamp2time(time_stamp)}_{replier_user_name}_{hash_save_token(media_url)}_reply.png'
                            if is_image:
                                media_url += '?format=png&name=4096x4096'
                            media_lst.append([media_url, _file_name, is_image])
                    except Exception as e:
                        print(e)

                _csv_info = [parent_tweet_url, replier_display_name, replier_user_name, reply_date, reply_content, reply_url, reply_favorite_count, reply_retweet_count, reply_reply_count]
                self.csv.write(_csv_info)

            if media_lst:   #整页媒体统一下载
                jobs = [(m[0], m[1], False, None) for m in media_lst]
                asyncio.run(download_many(self.api, jobs, max_concurrent_requests))

    def get_querystring(self):
        if search_advanced:
            self.querystring = search_advanced
            self.user_name = ''
        else:
            if '/status/' in self.target: #指定推文
                self.tweet_id = self.target.split('/status/')[-1]
                self.user_name = self.target.split('/')[3]
                return False
            else:   #指定用户
                self.user_name = self.target.split('@')[-1]
                if time_range:
                    self.since_time, self.until_time = time_range.split(':')
                    self.querystring = f"(from:{self.user_name}) min_replies:{min_replies} min_faves:{min_faves} min_retweets:{min_retweets} until:{self.until_time} since:{self.since_time}"
                else:
                    self.querystring = f"(from:{self.user_name}) min_replies:{min_replies} min_faves:{min_faves} min_retweets:{min_retweets}"
            return True

    def get_result(self):
        _headers = self.api.headers
        _headers['referer'] = f'https://twitter.com/search?q={quote(self.querystring)}&src=typed_query&f=media'

        def get_tweet_list(url, _headers):
            #返回 [(tweet_id, 作者screen_name)] 列表,便于构造正确的父推文 URL
            tweet_lst = []

            _path = get_url_path(url)
            url = url.replace('{', '%7B').replace('}', '%7D')
            self.api.headers['x-client-transaction-id'] = self.ct.generate_transaction_id(method='GET', path=_path)
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
                try:
                    if 'tweet-' in tweet['entryId']:
                        tweet_id = tweet['entryId'].split('tweet-')[-1]
                        screen_name = tweet['content']['itemContent']['tweet_results']['result']['core']['user_results']['result']['legacy']['screen_name']
                        tweet_lst.append((tweet_id, screen_name))
                except Exception:
                    continue
            return tweet_lst

        while True:
            url = 'https://x.com/i/api/graphql/yiE17ccAAu3qwM34bPYZkQ/SearchTimeline?variables={"rawQuery":"' + quote(self.querystring) + '","count":"20","cursor":"' + self.cursor + '","querySource":"typed_query","product":"Latest"}&features={"rweb_video_screen_enabled":false,"profile_label_improvements_pcf_label_in_post_enabled":true,"rweb_tipjar_consumption_enabled":true,"verified_phone_label_enabled":false,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_timeline_navigation_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"premium_content_api_read_enabled":false,"communities_web_enable_tweet_community_results_fetch":true,"c9s_tweet_anatomy_moderator_badge_enabled":true,"responsive_web_grok_analyze_button_fetch_trends_enabled":false,"responsive_web_grok_analyze_post_followups_enabled":true,"responsive_web_jetfuel_frame":false,"responsive_web_grok_share_attachment_enabled":true,"articles_preview_enabled":true,"responsive_web_edit_tweet_api_enabled":true,"graphql_is_translatable_rweb_tweet_is_translatable_enabled":true,"view_counts_everywhere_api_enabled":true,"longform_notetweets_consumption_enabled":true,"responsive_web_twitter_article_tweet_consumption_enabled":true,"tweet_awards_web_tipping_enabled":false,"responsive_web_grok_show_grok_translated_post":false,"responsive_web_grok_analysis_button_from_backend":false,"creator_subscriptions_quote_tweet_preview_enabled":false,"freedom_of_speech_not_reach_fetch_enabled":true,"standardized_nudges_misinfo":true,"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":true,"longform_notetweets_rich_text_read_enabled":true,"longform_notetweets_inline_media_enabled":true,"responsive_web_grok_image_annotation_enabled":true,"responsive_web_enhance_cards_enabled":false}'
            tweet_lst = get_tweet_list(url, _headers)
            if not tweet_lst:
                break
            for tweet_id, screen_name in tweet_lst:
                self.id2reply(tweet_id, screen_name)


if __name__ == '__main__':
    for _target in target_user:
        print(f'开始处理: {_target}')
        Reply_down(_target)
        print(f'处理完成: {_target}')
