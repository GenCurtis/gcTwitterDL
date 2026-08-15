import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 根目录,以导入 tw_dl/

from tw_dl.user_info import User_info
from tw_dl.utils import time2stamp, time_comparison, get_tweet_msecs
from tw_dl.api import TwitterAPI, RateLimitError, AuthError, TwitterAPIError
from tw_dl.csv_writer import CsvWriter


##########配置区域##########
cookie = 'auth_token=xxxxxxxxxxx; ct0=xxxxxxxxxxx;'
# 填入 cookie (auth_token与ct0字段) //重要:替换掉其中的x即可, 注意不要删掉分号

user_lst = ['jeleechandayo','yorukura_anime']
# 填入要下载的用户名(@后面的字符),支持多用户下载,在列表里添加即可

time_range = "2024-04-21:2030-01-01"
# 时间范围限制,格式如 1990-01-01:2030-01-01

has_retweet = False
# 是否包含转推

##########配置区域##########


start_time, end_time = time_range.split(':')
start_time_stamp, end_time_stamp = time2stamp(start_time), time2stamp(end_time)


class text_down():
    def __init__(self, screen_name):
        self._user_info = User_info(screen_name)

        self.api = TwitterAPI(cookie)

        try:
            if not self.get_other_info():
                return
            self.print_info()

            self.api.headers['referer'] = 'https://twitter.com/' + self._user_info.screen_name

            self.folder_path = os.getcwd() + os.sep + screen_name + os.sep

            if not os.path.exists(self.folder_path):   #创建文件夹
                os.makedirs(self.folder_path)

            self.csv_file = CsvWriter(
                self.folder_path,
                f'{screen_name}-{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}-text.csv',
                [[self._user_info.name, '@' + self._user_info.screen_name],
                 ['Tweet Range : ' + time_range],
                 ['Save Path : ' + self.folder_path]],
                ['Display Name', 'User Name', 'Tweet Date', 'Tweet URL', 'Tweet Content', 'Favorite Count',
                 'Retweet Count', 'Reply Count'],
                stamp_index=2,
            )

            self.cursor = ''

            self.get_clean_save()

            self.csv_file.close()
        finally:
            self.api.close()

    def get_other_info(self):
        url = 'https://twitter.com/i/api/graphql/xc8f1g7BYqr6VTzTbvNlGw/UserByScreenName?variables={"screen_name":"' + self._user_info.screen_name + '","withSafetyModeUserFields":false}&features={"hidden_profile_likes_enabled":false,"hidden_profile_subscriptions_enabled":false,"responsive_web_graphql_exclude_directive_enabled":true,"verified_phone_label_enabled":false,"subscriptions_verification_info_verified_since_enabled":true,"highlights_tweets_tab_ui_enabled":true,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"responsive_web_graphql_timeline_navigation_enabled":true}&fieldToggles={"withAuxiliaryUserLabels":false}'
        try:
            raw_data = self.api.get_json(url)
            self._user_info.rest_id = raw_data['data']['user']['result']['rest_id']
            self._user_info.name = raw_data['data']['user']['result']['legacy']['name']
            self._user_info.statuses_count = raw_data['data']['user']['result']['legacy']['statuses_count']
            self._user_info.media_count = raw_data['data']['user']['result']['legacy']['media_count']
        except (RateLimitError, AuthError, TwitterAPIError) as e:
            print('获取信息失败')
            print(e)
            return False
        except Exception as e:
            print(f'{self._user_info.screen_name}: 获取信息失败(响应结构异常)')
            print(e)
            return False
        return True

    def print_info(self):
        print(
            f'''
            <======基本信息=====>
            昵称:{self._user_info.name}
            用户名:{self._user_info.screen_name}
            数字ID:{self._user_info.rest_id}
            总推数(含转推):{self._user_info.statuses_count}
            含图片/视频/音频推数(不含转推):{self._user_info.media_count}
            <==================>
            开始爬取...
            '''
        )

    def get_clean_save(self):
        while True:
            ###get_all_data###
            url = 'https://twitter.com/i/api/graphql/9zyyd1hebl7oNWIPdA8HRw/UserTweets?variables={"userId":"' + self._user_info.rest_id + '","count":20,"cursor":"' + self.cursor + '","includePromotedContent":true,"withQuickPromoteEligibilityTweetFields":true,"withVoice":true,"withV2Timeline":true}&features={"rweb_tipjar_consumption_enabled":true,"responsive_web_graphql_exclude_directive_enabled":true,"verified_phone_label_enabled":false,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_timeline_navigation_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"communities_web_enable_tweet_community_results_fetch":true,"c9s_tweet_anatomy_moderator_badge_enabled":true,"articles_preview_enabled":true,"tweetypie_unmention_optimization_enabled":true,"responsive_web_edit_tweet_api_enabled":true,"graphql_is_translatable_rweb_tweet_is_translatable_enabled":true,"view_counts_everywhere_api_enabled":true,"longform_notetweets_consumption_enabled":true,"responsive_web_twitter_article_tweet_consumption_enabled":true,"tweet_awards_web_tipping_enabled":false,"creator_subscriptions_quote_tweet_preview_enabled":false,"freedom_of_speech_not_reach_fetch_enabled":true,"standardized_nudges_misinfo":true,"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":true,"tweet_with_visibility_results_prefer_gql_media_interstitial_enabled":true,"rweb_video_timestamps_enabled":true,"longform_notetweets_rich_text_read_enabled":true,"longform_notetweets_inline_media_enabled":true,"responsive_web_enhance_cards_enabled":false}&fieldToggles={"withArticlePlainText":false}'

            try:
                raw_data = self.api.get_json(url)
            except RateLimitError:
                print('API次数已超限')
                return
            except (AuthError, TwitterAPIError) as e:
                print('获取数据失败')
                print(e)
                return
            raw_tweet_lst = raw_data['data']['user']['result']['timeline_v2']['timeline']['instructions'][-1]['entries']
            if len(raw_tweet_lst) == 2:
                return
            if self.cursor == raw_tweet_lst[-1]['content']['value']:
                return
            self.cursor = raw_tweet_lst[-1]['content']['value']

            for tweet in raw_tweet_lst:
                if 'promoted-tweet' in tweet['entryId']:        #排除广告
                        continue
                if 'tweet' in tweet['entryId']:
                    raw_text = tweet['content']['itemContent']['tweet_results']['result']
                    if 'tweet' in raw_text:
                        raw_text = raw_text['tweet']
                    _time_stamp = get_tweet_msecs(raw_text)
                    if _time_stamp is None:
                        continue
                    if 'retweeted_status_result' in raw_text['legacy']:       #转推判断
                        if has_retweet:
                            raw_text = raw_text['legacy']['retweeted_status_result']['result']
                            if 'tweet' in raw_text:
                                raw_text = raw_text['tweet']
                            _display_name = raw_text['core']['user_results']['result']['legacy']['name']
                            _screen_name = '@' + raw_text['core']['user_results']['result']['legacy']['screen_name']
                        else:
                            continue
                    else:
                        _display_name = ''
                        _screen_name = ''

                    _results = time_comparison(_time_stamp, start_time_stamp, end_time_stamp)
                    if not _results[1]:     #超出时间范围，结束
                        return
                    if not _results[0]:     #不符合时间条件，跳过
                        continue

                    _Favorite_Count = raw_text['legacy']['favorite_count']
                    _Retweet_Count = raw_text['legacy']['retweet_count']
                    _Reply_Count = raw_text['legacy']['reply_count']
                    _status_id = raw_text['legacy']['id_str']
                    screen_name = raw_text['core']['user_results']['result']['legacy']['screen_name']
                    _tweet_url = f'https://twitter.com/{screen_name}/status/{_status_id}'
                    if 'note_tweet' in raw_text:
                        _tweet_content = raw_text['note_tweet']['note_tweet_results']['result']['text'].split('https://t.co/')[0]
                    else:
                        _tweet_content = raw_text['legacy']['full_text'].split('https://t.co/')[0]

                    self.csv_file.write([_display_name, _screen_name, _time_stamp, _tweet_url, _tweet_content, _Favorite_Count, _Retweet_Count, _Reply_Count])


if __name__ == '__main__':
    for user in user_lst:
        text_down(user)
    print('完成 (๑´ڡ`๑)')
