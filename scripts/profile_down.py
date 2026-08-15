import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 根目录,以导入 tw_dl/

from tw_dl.api import TwitterAPI, RateLimitError, AuthError, TwitterAPIError
from tw_dl.logger import logger


##########配置区域##########
cookie = 'auth_token=xxxxxxxxxxx; ct0=xxxxxxxxxxx;'
# 填入 cookie (auth_token与ct0字段) //重要:替换掉其中的x即可, 注意不要删掉分号

user_lst = ['jeleechandayo','matchach','lilmonix3']
# 填入要下载的用户名(@后面的字符),支持多用户下载,在列表里添加即可

##########配置区域##########


_path = 'profile'


def profile_down(screen_name, path):
    api = TwitterAPI(cookie)
    try:
        api.headers['referer'] = 'https://twitter.com/' + screen_name

        url = 'https://twitter.com/i/api/graphql/gEyDv8Fmv2BVTYIAf32nbA/UserByScreenName?variables={"screen_name":"' + screen_name + '","withGrokTranslatedBio":false}&features={"hidden_profile_subscriptions_enabled":true,"payments_enabled":false,"rweb_xchat_enabled":false,"profile_label_improvements_pcf_label_in_post_enabled":true,"rweb_tipjar_consumption_enabled":true,"verified_phone_label_enabled":false,"subscriptions_verification_info_is_identity_verified_enabled":true,"subscriptions_verification_info_verified_since_enabled":true,"highlights_tweets_tab_ui_enabled":true,"responsive_web_twitter_article_notes_tab_enabled":true,"subscriptions_feature_can_gift_premium":true,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"responsive_web_graphql_timeline_navigation_enabled":true}&fieldToggles={"withAuxiliaryUserLabels":true}'
        raw_data = api.get_json(url)
        avatar_url = raw_data['data']['user']['result']['avatar']['image_url']
        description = raw_data['data']['user']['result']['legacy']['description']
        if 'profile_banner_url' not in raw_data['data']['user']['result']['legacy']:
            profile_banner_url = None
        else:
            profile_banner_url = raw_data['data']['user']['result']['legacy']['profile_banner_url']

        avatar_url = re.sub(r'_normal(\.\w+)$', r'_400x400\1', avatar_url)

        # 检查响应状态码,避免把 404 页面字节存成 jpg
        avatar_response = api.client.get(avatar_url)
        if avatar_response.status_code == 200:
            with open(_path + os.sep + screen_name + '_avatar.jpg', 'wb') as f:
                f.write(avatar_response.content)
        else:
            logger.warning(f'{screen_name} 头像下载失败: HTTP {avatar_response.status_code}')

        if profile_banner_url:
            banner_response = api.client.get(profile_banner_url)
            if banner_response.status_code == 200:
                with open(_path + os.sep + screen_name + '_banner.jpg', 'wb') as f:
                    f.write(banner_response.content)
            else:
                logger.warning(f'{screen_name} banner下载失败: HTTP {banner_response.status_code}')

        with open(_path + os.sep + screen_name + '_description.txt', 'w', encoding='utf-8') as f:
            f.write(description)

    except (RateLimitError, AuthError, TwitterAPIError) as e:
        print(f'用户: {screen_name}  失败: {e}')
        return False
    except Exception as e:
        print(f'用户: {screen_name}  失败(响应结构异常): {e}')
        return False
    finally:
        api.close()
    return True


if __name__ == '__main__':
    if not os.path.exists(_path):
        os.makedirs(_path)
    for user in user_lst:
        print(f'\n正在获取用户: {user}')
        if profile_down(user, _path):
            print('---------Completed---------')

    print('\nAll tasks completed.')
