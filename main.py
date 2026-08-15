import re
import time
import asyncio
import os
import sys
import json
from datetime import datetime

sys.path.append('.')
from tw_dl.user_info import User_info
from tw_dl.utils import stamp2time, time2stamp, time_comparison, get_tweet_msecs, get_highest_video_quality, check_user_status
from tw_dl.config import config
from tw_dl.api import TwitterAPI, RateLimitError, AuthError, TwitterAPIError, ResponseStructureError
from tw_dl.csv_writer import CsvWriter
from tw_dl.md_writer import MdWriter
from tw_dl.cache import DownloadCache
from tw_dl.downloader import download_many
from tw_dl.archive import archive_suspended_user
from tw_dl.logger import logger
from tw_dl.dedup import DedupIndex

backup_stamp = 655028357000   # 1990-10-04

start_label = True       # 是否仍在目标时间范围内
First_Page = True        # 首页提取内容时特殊处理

request_count = 0    # 请求次数计数
down_count = 0       # 下载图片数计数


def _load_sync_state_cache():
    """读 sync_down 的 _sync_state.json 拿 rest_id/name 缓存,命中则免一次 UserByScreenName 调用。
    返回 {screen_name: (rest_id, name)};文件缺失/损坏/无该用户 → 空字典,调用方回退。"""
    try:
        path = os.path.join(config.save_path, '_sync_state.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return {u: (v.get('rest_id'), v.get('name')) for u, v in data.items()
                if isinstance(v, dict) and v.get('rest_id')}
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return {}


def get_other_info(_user_info, api):
    # 返回状态:'ok' / 'suspended'(封号或注销) / 'not_found' / 'error'
    cached = _load_sync_state_cache().get(_user_info.screen_name)
    if cached:
        # 配额压缩:sync_down 已缓存 rest_id/name,免调 UserByScreenName(展示字段留空,print_info 容忍)
        _user_info.rest_id, _user_info.name = cached[0], cached[1] or _user_info.screen_name
        return 'ok'
    url = 'https://twitter.com/i/api/graphql/xc8f1g7BYqr6VTzTbvNlGw/UserByScreenName?variables={"screen_name":"' + _user_info.screen_name + '","withSafetyModeUserFields":false}&features={"hidden_profile_likes_enabled":false,"hidden_profile_subscriptions_enabled":false,"responsive_web_graphql_exclude_directive_enabled":true,"verified_phone_label_enabled":false,"subscriptions_verification_info_verified_since_enabled":true,"highlights_tweets_tab_ui_enabled":true,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"responsive_web_graphql_timeline_navigation_enabled":true}&fieldToggles={"withAuxiliaryUserLabels":false}'
    try:
        global request_count
        raw_data = api.get_json(url)
        request_count += 1
        result = raw_data['data']['user']['result']
        status = check_user_status(result)
        if status == 'not_found':
            print(f'{_user_info.screen_name}: 用户不存在或已注销')
            return 'not_found'
        if status == 'suspended':
            print(f'{_user_info.screen_name}: 用户已被封号({result.get("__typename", "")})')
            return 'suspended'
        _user_info.rest_id = result['rest_id']
        _user_info.name = result['legacy']['name']
        _user_info.statuses_count = result['legacy']['statuses_count']
        _user_info.media_count = result['legacy']['media_count']
    except (RateLimitError, AuthError, TwitterAPIError) as e:
        print('获取信息失败')
        print(e)
        if isinstance(e, RateLimitError):
            _user_info.last_error = 'rate_limit'
        elif isinstance(e, AuthError):
            _user_info.last_error = 'auth'
        else:
            _user_info.last_error = 'structure'
        return 'error'
    except Exception as e:
        print(f'{_user_info.screen_name}: 获取信息失败(响应结构异常)')
        print(e)
        _user_info.last_error = 'structure'
        return 'error'
    return 'ok'


def print_info(_user_info):
    # 缓存命中时 statuses_count/media_count 可能为 None,显示 '未知'
    print(
        f'''
        <======基本信息=====>
        昵称:{_user_info.name}
        用户名:{_user_info.screen_name}
        数字ID:{_user_info.rest_id}
        总推数(含转推):{_user_info.statuses_count if _user_info.statuses_count is not None else '未知(缓存)'}
        含图片/视频/音频推数(不含转推):{_user_info.media_count if _user_info.media_count is not None else '未知(缓存)'}
        <==================>
        开始爬取...
        '''
    )


def get_download_url(_user_info, api):

    def get_url_from_content(content):
        global start_label
        _photo_lst = []
        if config.has_retweet or config.has_highlights:
            x_label = 'content'
        else:
            x_label = 'item'
        for i in content:
            try:
                if 'promoted-tweet' in i['entryId']:        # 排除广告
                    continue
                if 'tweet' in i['entryId']:     # 正常推文
                    result = i[x_label]['itemContent']['tweet_results']['result']
                    if 'tweet' in result:       # 适配限制回复账号
                        result = result['tweet']
                    a = result['legacy']
                    frr = [a['favorite_count'], a['retweet_count'], a['reply_count']]
                    tweet_msecs = get_tweet_msecs(result)
                    if tweet_msecs is None:
                        continue
                    timestr = stamp2time(tweet_msecs)

                    _result = time_comparison(tweet_msecs, config.start_stamp, config.end_stamp)
                    if _result[0]:  # 符合时间限制
                        if 'retweeted_status_result' not in a:  # 判断是否为转推,以及是否获取转推
                            name = _user_info.name
                            screen_name = _user_info.screen_name
                            if config.has_likes:
                                a2 = result['core']['user_results']['result']['legacy']
                                name = a2['name']
                                screen_name = a2['screen_name']
                            if 'extended_entities' in a:
                                # 文件名:时间-推文ID-类型+图序号(推文ID稳定,删帖重拉不漂移;同推文多图可分组)
                                status_id = result['rest_id']
                                _photo_lst += [(get_highest_video_quality(m['video_info']['variants']), f'{timestr}-{status_id}-vid{idx}', [tweet_msecs, name, f'@{screen_name}', m['expanded_url'], 'Video', get_highest_video_quality(m['video_info']['variants']), '', a['full_text']] + frr) if 'video_info' in m and config.has_video else (m['media_url_https'], f'{timestr}-{status_id}-img{idx}', [tweet_msecs, name, f'@{screen_name}', m['expanded_url'], 'Image', m['media_url_https'], '', a['full_text']] + frr) for idx, m in enumerate(a['extended_entities']['media'])]

                        elif config.has_retweet:
                            name = a['retweeted_status_result']['result']['core']['user_results']['result']['legacy']['name']
                            screen_name = a['retweeted_status_result']['result']['core']['user_results']['result']['legacy']['screen_name']
                            full_text = a['retweeted_status_result']['result']['legacy']['full_text']
                            id_str = a['retweeted_status_result']['result']['legacy']['id_str']

                            if 'extended_entities' in a['retweeted_status_result']['result']['legacy'] and screen_name != _user_info.screen_name:
                                _photo_lst += [(get_highest_video_quality(m['video_info']['variants']), f'{timestr}-{id_str}-vid{idx}-retweet', [tweet_msecs, name, f"@{screen_name}", m['expanded_url'], 'Video', get_highest_video_quality(m['video_info']['variants']), '', full_text] + frr) if 'video_info' in m and config.has_video else (m['media_url_https'], f'{timestr}-{id_str}-img{idx}-retweet', [tweet_msecs, name, f"@{screen_name}", m['expanded_url'], 'Image', m['media_url_https'], '', full_text] + frr) for idx, m in enumerate(a['retweeted_status_result']['result']['legacy']['extended_entities']['media'])]

                    elif not _result[1]:    # 已超出目标时间范围
                        start_label = False
                        break

                elif 'profile-conversation' in i['entryId']:    # 回复的推文(对话线索)
                    result = i[x_label]['items'][0]['item']['itemContent']['tweet_results']['result']
                    if 'tweet' in result:
                        result = result['tweet']
                    a = result['legacy']
                    frr = [a['favorite_count'], a['retweet_count'], a['reply_count']]
                    tweet_msecs = get_tweet_msecs(result)
                    if tweet_msecs is None:
                        continue
                    timestr = stamp2time(tweet_msecs)

                    _result = time_comparison(tweet_msecs, config.start_stamp, config.end_stamp)
                    if _result[0]:  # 符合时间限制
                        if 'extended_entities' in a:
                            status_id = result['rest_id']
                            _photo_lst += [(get_highest_video_quality(m['video_info']['variants']), f'{timestr}-{status_id}-vid{idx}', [tweet_msecs, _user_info.name, f'@{_user_info.screen_name}', m['expanded_url'], 'Video', get_highest_video_quality(m['video_info']['variants']), '', a['full_text']] + frr) if 'video_info' in m and config.has_video else (m['media_url_https'], f'{timestr}-{status_id}-img{idx}', [tweet_msecs, _user_info.name, f'@{_user_info.screen_name}', m['expanded_url'], 'Image', m['media_url_https'], '', a['full_text']] + frr) for idx, m in enumerate(a['extended_entities']['media'])]
                    elif not _result[1]:    # 已超出目标时间范围
                        start_label = False
                        break

            except Exception as e:
                logger.debug(f'条目解析失败,已跳过: {e}', exc_info=True)  # R3:静默容错留痕
                continue
            if 'cursor-bottom' in i['entryId']:     # 更新下一页的请求编号(含转推模式&亮点模式)
                _user_info.cursor = i['content']['value']

        return _photo_lst

    print(f'已下载图片/视频:{_user_info.count}')
    if config.has_highlights: ##2024-01-05 #适配[亮点]标签
        url_top = 'https://twitter.com/i/api/graphql/w9-i9VNm_92GYFaiyGT1NA/UserHighlightsTweets?variables={"userId":"' + _user_info.rest_id + '","count":20,'
        url_bottom = '"includePromotedContent":true,"withVoice":true}&features={"responsive_web_graphql_exclude_directive_enabled":true,"verified_phone_label_enabled":false,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_timeline_navigation_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"c9s_tweet_anatomy_moderator_badge_enabled":true,"tweetypie_unmention_optimization_enabled":true,"responsive_web_edit_tweet_api_enabled":true,"graphql_is_translatable_rweb_tweet_is_translatable_enabled":true,"view_counts_everywhere_api_enabled":true,"longform_notetweets_consumption_enabled":true,"responsive_web_twitter_article_tweet_consumption_enabled":false,"tweet_awards_web_tipping_enabled":false,"freedom_of_speech_not_reach_fetch_enabled":true,"standardized_nudges_misinfo":true,"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":true,"rweb_video_timestamps_enabled":true,"longform_notetweets_rich_text_read_enabled":true,"longform_notetweets_inline_media_enabled":true,"responsive_web_media_download_video_enabled":false,"responsive_web_enhance_cards_enabled":false}'
    elif config.has_likes:
        url_top = 'https://twitter.com/i/api/graphql/-fbTO1rKPa3nO6-XIRgEFQ/Likes?variables={"userId":"' + _user_info.rest_id + '","count":200,'
        url_bottom = '"includePromotedContent":false,"withClientEventToken":false,"withBirdwatchNotes":false,"withVoice":true,"withV2Timeline":true}&features={"responsive_web_graphql_exclude_directive_enabled":true,"verified_phone_label_enabled":false,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_timeline_navigation_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"c9s_tweet_anatomy_moderator_badge_enabled":true,"tweetypie_unmention_optimization_enabled":true,"responsive_web_edit_tweet_api_enabled":true,"graphql_is_translatable_rweb_tweet_is_translatable_enabled":true,"view_counts_everywhere_api_enabled":true,"longform_notetweets_consumption_enabled":true,"responsive_web_twitter_article_tweet_consumption_enabled":false,"tweet_awards_web_tipping_enabled":false,"freedom_of_speech_not_reach_fetch_enabled":true,"standardized_nudges_misinfo":true,"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":true,"rweb_video_timestamps_enabled":true,"longform_notetweets_rich_text_read_enabled":true,"longform_notetweets_inline_media_enabled":true,"responsive_web_media_download_video_enabled":false,"responsive_web_enhance_cards_enabled":false}'
    elif config.has_retweet:     # 包含转推调用[UserTweets]的API(调用一次上限返回20条)
        url_top = 'https://twitter.com/i/api/graphql/2GIWTr7XwadIixZDtyXd4A/UserTweets?variables={"userId":"' + _user_info.rest_id + '","count":20,'
        url_bottom = '"includePromotedContent":false,"withQuickPromoteEligibilityTweetFields":true,"withVoice":true,"withV2Timeline":true}&features={"rweb_lists_timeline_redesign_enabled":true,"responsive_web_graphql_exclude_directive_enabled":true,"verified_phone_label_enabled":false,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_timeline_navigation_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"tweetypie_unmention_optimization_enabled":true,"responsive_web_edit_tweet_api_enabled":true,"graphql_is_translatable_rweb_tweet_is_translatable_enabled":true,"view_counts_everywhere_api_enabled":true,"longform_notetweets_consumption_enabled":true,"responsive_web_twitter_article_tweet_consumption_enabled":false,"tweet_awards_web_tipping_enabled":false,"freedom_of_speech_not_reach_fetch_enabled":true,"standardized_nudges_misinfo":true,"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":true,"rweb_video_timestamps_enabled":true,"longform_notetweets_rich_text_read_enabled":true,"longform_notetweets_inline_media_enabled":true,"responsive_web_media_download_video_enabled":false,"responsive_web_enhance_cards_enabled":false}&fieldToggles={"withAuxiliaryUserLabels":false,"withArticleRichContentState":false}'
    else:       # 不包含转推则调用[UserMedia]的API(返回条数貌似无上限/改count) ##2023-12-11#此模式API返回值变动
        url_top = 'https://twitter.com/i/api/graphql/Le6KlbilFmSu-5VltFND-Q/UserMedia?variables={"userId":"' + _user_info.rest_id + '","count":500,'
        url_bottom = '"includePromotedContent":false,"withClientEventToken":false,"withBirdwatchNotes":false,"withVoice":true,"withV2Timeline":true}&features={"responsive_web_graphql_exclude_directive_enabled":true,"verified_phone_label_enabled":false,"creator_subscriptions_tweet_preview_api_enabled":true,"responsive_web_graphql_timeline_navigation_enabled":true,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,"tweetypie_unmention_optimization_enabled":true,"responsive_web_edit_tweet_api_enabled":true,"graphql_is_translatable_rweb_tweet_is_translatable_enabled":true,"view_counts_everywhere_api_enabled":true,"longform_notetweets_consumption_enabled":true,"responsive_web_twitter_article_tweet_consumption_enabled":false,"tweet_awards_web_tipping_enabled":false,"freedom_of_speech_not_reach_fetch_enabled":true,"standardized_nudges_misinfo":true,"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":true,"rweb_video_timestamps_enabled":true,"longform_notetweets_rich_text_read_enabled":true,"longform_notetweets_inline_media_enabled":true,"responsive_web_media_download_video_enabled":false,"responsive_web_enhance_cards_enabled":false}'

    if _user_info.cursor:
        url = url_top + '"cursor":"' + _user_info.cursor + '",' + url_bottom
    else:
        url = url_top + url_bottom      # 第一页,无cursor
    try:
        global request_count
        raw_data = api.get_json(url)
        request_count += 1
    except RateLimitError:
        print('API次数已超限')
        raise
    except (AuthError, TwitterAPIError) as e:
        print('获取数据失败')
        print(e)
        raise
    try:
        if config.has_highlights:  # 亮点模式
            raw_data = raw_data['data']['user']['result']['timeline']['timeline']['instructions'][-1]['entries']
        elif config.has_retweet:   # 与likes共用
            raw_data = raw_data['data']['user']['result']['timeline_v2']['timeline']['instructions'][-1]['entries']
        else:   # usermedia模式
            raw_data = raw_data['data']['user']['result']['timeline_v2']['timeline']['instructions']
        if (config.has_retweet or config.has_highlights) and 'cursor-top' in raw_data[0]['entryId']:      # 含转推模式 所有推文已全部下载完成
            return False

        if not config.has_retweet and not config.has_highlights:     # usermedia模式下的下一页请求编号
            for i in raw_data[-1]['entries']:
                if 'bottom' in i['entryId']:
                    _user_info.cursor = i['content']['value']

        if start_label:     # 判断是否超出时间范围
            if not config.has_retweet and not config.has_highlights:
                global First_Page
                if First_Page:   # 第一页的返回值需特殊处理
                    raw_data = raw_data[-1]['entries'][0]['content']['items']
                    First_Page = False
                else:
                    if 'moduleItems' not in raw_data[0]:    # usermedia新模式，所有推文已全部下载完成
                        return False
                    else:
                        raw_data = raw_data[0]['moduleItems']
            photo_lst = get_url_from_content(raw_data)
        else:
            return False

        if not photo_lst:
            photo_lst.append(True)
    except Exception as e:
        print('获取推文信息错误')
        print(e)
        # 结构异常必须与「正常拉完」区分:raise 后 main() 返回 False,
        # sync_down 不会把本次记为已同步(曾把结构变动静默记为完成 → 永不重试 → 内容永久缺失)
        raise ResponseStructureError(f'响应结构解析失败: {e}') from e
    return photo_lst


def download_control(_user_info, api, csv_file, md_file, cache_data):

    def build_jobs(photo_lst):
        # 构造下载任务:处理文件名与格式参数;返回 [(url, filename, fallback, (csv_info, prefix))]
        # 文件名 = {时间戳}-{推文ID}-{img/vid}{图序号}:推文 ID 稳定,删帖重拉不漂移,多图可分组
        jobs = []
        for url in photo_lst:
            media_url, prefix, csv_info = url[0], url[1], url[2]
            if '.mp4' in media_url:
                filename = f'{_user_info.save_path + os.sep}{prefix}.mp4'
                final_url, fallback = media_url, False
            else:
                try:
                    if config.orig_format:
                        final_url = media_url + '?name=orig'
                        filename = f'{_user_info.save_path + os.sep}{prefix}.{csv_info[5][-3:]}'  # 根据图片 url 获取原始格式
                        fallback = True   # 404 时降级 4096x4096
                    else:  # 指定格式时直接使用 4096x4096 保证最大尺寸
                        filename = f'{_user_info.save_path + os.sep}{prefix}.{config.img_format}'
                        final_url = media_url + (f'?format=png&name=4096x4096' if config.img_format == 'png' else '?format=jpg&name=4096x4096')
                        fallback = False
                except Exception as e:
                    print(media_url)
                    continue
            csv_info[-5] = os.path.split(filename)[1]
            jobs.append((final_url, filename, fallback, (csv_info, prefix)))
        return jobs

    def md_pre_hook(url, filename, extra):
        # 下载前输出到 Markdown,保证高并发下推文顺序正确
        csv_info, prefix = extra
        if config.md_output:
            md_file.media_tweet_input(csv_info, prefix)

    def csv_post_hook(url, filename, extra):
        global down_count
        csv_info, prefix = extra
        down_count += 1
        csv_file.write(csv_info)
        if config.down_log:
            cache_data.mark(url)    # 仅成功下载后才登记缓存(失败的下次重试)
        if config.log_output:
            print(f'{filename}=====>下载完成')

    async def _main():
        api.ensure_async_client()   # 循环内创建,循环内关闭
        dedup = DedupIndex(config.save_path, config.alias, _user_info.screen_name) if config.content_dedup else None
        try:
            prev_cursor = None
            first = True
            while True:
                before = _user_info.cursor
                try:
                    photo_lst = get_download_url(_user_info, api)
                except (RateLimitError, AuthError, TwitterAPIError) as e:
                    print(f'拉取中断: {e}')
                    if isinstance(e, RateLimitError):
                        _user_info.last_error = 'rate_limit'
                    elif isinstance(e, AuthError):
                        _user_info.last_error = 'auth'
                    else:
                        _user_info.last_error = 'structure'
                    return False
                except Exception as e:
                    print(f'拉取出错: {e}')
                    _user_info.last_error = 'error'
                    return False
                if not photo_lst:
                    break
                if not first and _user_info.cursor == before:
                    # cursor 未推进:下一页将重复返回本页内容,再拉只会烧配额(曾会死循环)
                    print('警告: cursor 未推进,疑似响应结构变动,提前结束本次拉取')
                    break
                first = False
                if photo_lst[0] is True:
                    continue
                jobs = build_jobs(photo_lst)
                if config.down_log:
                    jobs = [j for j in jobs if not cache_data.is_downloaded(j[0])]
                await download_many(api, jobs, config.max_concurrent_requests,
                                    pre_hook=md_pre_hook, post_hook=csv_post_hook, dedup=dedup)
                _user_info.count += len(photo_lst)      # 更新计数
            return True
        finally:
            await api.aclose()

    return asyncio.run(_main())


def main(_user_info):
    # 返回 True = 本次拉取完整完成;False = 失败/中断(配额、认证、异常),调用方(如 sync_down)可据此决定是否记状态
    # 模块级全局是「每次调用」的解析状态,必须在入口复位——sync_down 等外部调用方不会帮忙复位
    global start_label, First_Page
    start_label = True
    First_Page = True
    api = TwitterAPI(config.cookie, config.proxies)
    try:
        status = get_other_info(_user_info, api)
        if status == 'suspended':
            archive_suspended_user(_user_info.screen_name, config.save_path)
            logger.info(f'{_user_info.screen_name} 被封号,已归档')
            return False
        if status != 'ok':
            logger.info(f'{_user_info.screen_name} 拉取失败(跳过): {status}')
            return False
        logger.info(f'开始拉取 {_user_info.screen_name}(rest_id={_user_info.rest_id})')
        print_info(_user_info)
        _path = config.save_path + os.sep + _user_info.screen_name
        if not os.path.exists(_path):   # 创建文件夹
            os.makedirs(_path)          # 用户名建文件夹
        _user_info.save_path = _path

        csv_file = CsvWriter(
            _path,
            f'{_user_info.screen_name}-{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.csv',
            [[_user_info.name, _user_info.screen_name],
             ['Tweet Range : ' + (config.time_range or '无限制')],
             ['Save Path : ' + _path]],
            ['Tweet Date', 'Display Name', 'User Name', 'Tweet URL', 'Media Type', 'Media URL',
             'Saved Filename', 'Tweet Content', 'Favorite Count', 'Retweet Count', 'Reply Count'],
            stamp_index=0,
        )
        md_file = MdWriter(_path, _user_info.name, _user_info.screen_name,
                           config.time_range, config.has_likes, config.media_count_limit) if config.md_output else None
        cache_data = DownloadCache(_path) if config.down_log else None

        if config.autoSync:
            files = sorted(os.listdir(_user_info.save_path))
            if len(files) > 0:
                re_rule = r'\d{4}-\d{2}-\d{2}'
                config.start_stamp = backup_stamp
                for i in files[::-1]:
                    if "-img_" in i:
                        config.start_stamp = time2stamp(re.findall(re_rule, i)[0])
                        break
                    elif "-vid_" in i:
                        config.start_stamp = time2stamp(re.findall(re_rule, i)[0])
                        break
            else:
                config.start_stamp = backup_stamp

        ok = download_control(_user_info, api, csv_file, md_file, cache_data)

        csv_file.close()

        if md_file:
            md_file.md_close()
        logger.info(f'{_user_info.screen_name} 拉取结束: 结果={ok}, 媒体={_user_info.count}')
        print(f'{_user_info.name}下载完成\n\n')
        return ok
    finally:
        api.close()


if __name__ == '__main__':
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    _start = time.time()
    for i in config.user_list:
        main(User_info(i))      # 全局状态已在 main() 内部复位
    print(f'共耗时:{time.time()-_start}秒\n共调用{request_count}次API\n共下载{down_count}份图片/视频')
