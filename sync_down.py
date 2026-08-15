# -*- coding: utf-8 -*-
# 增量拉取(自用 fork 新增):不遍历式全量拉取所有用户,而是对每个用户做一次轻量侦测,
# 有变化的用户才进入 main.py 的增量流程(autoSync 基于本地文件设定起点)。
#
# 变化侦测:UserMedia 第一页的「最新媒体推文 ID」(snowflake,单调递增)。
# - 用户删一条发一条 → 数量不变但 ID 变大 → 仍能侦测(数量类信号会漏)
# - 用户删帖导致 ID 回退 → 触发一次空增量,不丢数据,状态随之收敛
# - 纯文本新推文不改变媒体 ID → 不误触发
# rest_id 缓存在状态文件里,常态下每用户只需 1 次 API 调用;只有首次(或 rest_id 失效)
# 才额外调用一次 UserByScreenName 获取 rest_id 并顺带做封号检测。
#
# 用法:
#   配置 settings.json(user_lst / cookie / save_path),然后:
#   python sync_down.py
# 定时(每半天):Windows 计划任务 schtasks /create /tn TwitterSync /tr "python sync_down.py" /sc HOURLY /mo 12
#
# 状态文件:downloads/_sync_state.json — {用户名: {rest_id, latest_media_id, checked_at}};
# 删除该文件会强制下次对每个用户重新建立基线(全量拉取一遍,耗配额)。
# 封号侦测:UserMedia/UserByScreenName 返回 UserUnavailable/Tombstone → 自动归档为
# 「【已封号】用户名」(见 tw_dl/archive.py)。
import os
import sys
import json
import time
import hashlib
import argparse
import re
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tw_dl.config import config
from tw_dl.api import TwitterAPI, RateLimitError, AuthError, TwitterAPIError
from tw_dl.archive import archive_suspended_user
from tw_dl.logger import logger
from tw_dl.utils import extract_latest_media_id, check_user_status
from tw_dl.user_info import User_info
from main import main

STATE_FILE = os.path.join(config.save_path, '_sync_state.json')

# 与 main.py 保持一致:query id 失效时从 x.com 网页端重新获取
USER_INFO_URL = ('https://twitter.com/i/api/graphql/xc8f1g7BYqr6VTzTbvNlGw/UserByScreenName?variables={'
                 '"screen_name":"{user}","withSafetyModeUserFields":false}&features={'
                 '"hidden_profile_likes_enabled":false,"hidden_profile_subscriptions_enabled":false,'
                 '"responsive_web_graphql_exclude_directive_enabled":true,"verified_phone_label_enabled":false,'
                 '"subscriptions_verification_info_verified_since_enabled":true,"highlights_tweets_tab_ui_enabled":true,'
                 '"creator_subscriptions_tweet_preview_api_enabled":true,'
                 '"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,'
                 '"responsive_web_graphql_timeline_navigation_enabled":true}&fieldToggles={'
                 '"withAuxiliaryUserLabels":false}')
USER_MEDIA_URL = ('https://twitter.com/i/api/graphql/Le6KlbilFmSu-5VltFND-Q/UserMedia?variables={'
                  '"userId":"{rest_id}","count":20,"includePromotedContent":false,'
                  '"withClientEventToken":false,"withBirdwatchNotes":false,"withVoice":true,'
                  '"withV2Timeline":true}&features={"responsive_web_graphql_exclude_directive_enabled":true,'
                  '"verified_phone_label_enabled":false,"creator_subscriptions_tweet_preview_api_enabled":true,'
                  '"responsive_web_graphql_timeline_navigation_enabled":true,'
                  '"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,'
                  '"tweetypie_unmention_optimization_enabled":true,"responsive_web_edit_tweet_api_enabled":true,'
                  '"graphql_is_translatable_rweb_tweet_is_translatable_enabled":true,'
                  '"view_counts_everywhere_api_enabled":true,"longform_notetweets_consumption_enabled":true,'
                  '"responsive_web_twitter_article_tweet_consumption_enabled":false,'
                  '"tweet_awards_web_tipping_enabled":false,"freedom_of_speech_not_reach_fetch_enabled":true,'
                  '"standardized_nudges_misinfo":true,'
                  '"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":true,'
                  '"rweb_video_timestamps_enabled":true,"longform_notetweets_rich_text_read_enabled":true,'
                  '"longform_notetweets_inline_media_enabled":true,'
                  '"responsive_web_media_download_video_enabled":false,'
                  '"responsive_web_enhance_cards_enabled":false}')


def load_state():
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(config.save_path, exist_ok=True)
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def fetch_latest_media_id(api, rest_id):
    """1 次 UserMedia 调用 → (status, latest_media_id | None)"""
    # 注意:URL 含字面量 {"userId":...},必须用 replace 而非 format(format 会把它当字段解析而抛 KeyError)
    url = USER_MEDIA_URL.replace('{rest_id}', rest_id)
    try:
        raw_data = api.get_json(url)
    except RateLimitError:
        print('API次数已超限')
        return 'error', None
    except (AuthError, TwitterAPIError) as e:
        print(f'侦测失败: {e}')
        return 'error', None
    except Exception as e:
        print(f'侦测失败(响应结构异常): {e}')
        return 'error', None

    try:
        result = raw_data['data']['user']['result']
    except (KeyError, TypeError):
        return 'error', None
    status = check_user_status(result)
    if status != 'ok':
        return status, None
    return 'ok', extract_latest_media_id(raw_data)


def check_by_screen_name(api, user):
    """首次/rest_id 失效时:UserByScreenName 拿 rest_id + 封号检测 → (status, rest_id, name | None)"""
    url = USER_INFO_URL.replace('{user}', user)
    try:
        raw_data = api.get_json(url)
    except RateLimitError:
        print('API次数已超限')
        return 'error', None, None
    except (AuthError, TwitterAPIError) as e:
        print(f'{user}: 侦测失败: {e}')
        return 'error', None, None
    except Exception as e:
        print(f'{user}: 侦测失败(响应结构异常): {e}')
        return 'error', None, None

    try:
        result = raw_data['data']['user']['result']
    except (KeyError, TypeError):
        return 'error', None, None
    status = check_user_status(result)
    if status != 'ok':
        return status, None, None
    try:
        # name 顺带缓存:main.py 全量模式读此文件可省掉自己的 UserByScreenName 调用
        return 'ok', result['rest_id'], result['legacy']['name']
    except (KeyError, TypeError):
        return 'error', None, None


def check_user(api, user, entry):
    """轻量侦测入口:有缓存 rest_id → 1 次 UserMedia;否则 UserByScreenName + UserMedia(首次/重建)。
    返回 (status, rest_id, latest_media_id, name|None)"""
    rest_id = (entry or {}).get('rest_id')
    if rest_id:
        status, latest = fetch_latest_media_id(api, rest_id)
        if status in ('ok', 'suspended', 'not_found'):
            return status, rest_id, latest, (entry or {}).get('name')
        # error:可能是 rest_id 失效,回退重建
    status, rest_id, name = check_by_screen_name(api, user)
    if status != 'ok':
        return status, None, None, None
    status, latest = fetch_latest_media_id(api, rest_id)
    return status, rest_id, latest, name


def sync():
    users = config.user_list
    print(f'==== 增量拉取开始: {len(users)} 个用户,状态文件: {STATE_FILE} ====')
    if not config.cookie or 'ct0=' not in config.cookie:
        print('请先在 settings.json 配置 cookie(auth_token 与 ct0)')
        return
    config.autoSync = True  # 增量拉取基于本地已有文件
    if config.alias:
        for group, members in config.alias.items():
            print(f'别名组「{group}」: {members}')
    _print_alias_candidates()  # 换号/同人识别:仅提示,人工用 alias 命令确认

    api = TwitterAPI(config.cookie, config.proxies)
    state = load_state()
    changed = False
    try:
        for user in users:
            entry = state.get(user, {})
            status, rest_id, latest, name = check_user(api, user, entry)
            if status == 'suspended':
                archive_suspended_user(user, config.save_path)
                _hint_alias(user)
                if user in state:
                    del state[user]
                    save_state(state)
                continue
            if status == 'not_found':
                # 状态感知归档:曾正常存在(状态文件里有 rest_id)的用户现在取不到信息
                # → 疑似封号/注销,归档。免疫封号枚举漂移:枚举改了名字,「曾经存在+现在消失」仍成立
                if entry.get('rest_id'):
                    archive_suspended_user(user, config.save_path)
                    _hint_alias(user)
                    if user in state:
                        del state[user]
                        save_state(state)
                    print(f'{user}: 疑似封号/注销(result=None 但有历史记录),已归档')
                    continue
                print(f'{user}: 用户不存在,跳过')
                continue
            if status == 'error':
                print(f'{user}: 侦测失败,本次跳过(下次重试)')
                continue
            if latest is None:
                # 用户无媒体推文,或响应结构解析失败:保守跳过,不触发空增量
                print(f'{user}: 无媒体推文或无法解析最新媒体 ID,跳过')
                continue

            prev = entry.get('latest_media_id')
            if prev is not None and latest <= prev:
                # ID 单调递增:latest <= prev 说明用户删了媒体帖且无新帖(或 ID 回退),
                # 判定无变化——「删一条发一条」时最新 ID 必然 > prev,仍会触发
                print(f'{user}: 无新媒体推文(latest_id={latest}),跳过')
                continue

            print(f'{user}: 检测到新媒体变化({prev} -> {latest}),执行增量拉取...')
            ui = User_info(user)
            try:
                ok = main(ui)
            except Exception as e:
                print(f'{user}: 拉取异常: {e}')
                ok = False
                ui.last_error = 'error'
            if ok:
                # 完整完成才更新状态;失败(配额/中断)不记,下次重试
                new_entry = {'rest_id': rest_id, 'latest_media_id': latest,
                             'checked_at': time.strftime('%Y-%m-%d %H:%M:%S')}
                if name:
                    new_entry['name'] = name  # main.py 全量模式读此字段可省 UserByScreenName
                state[user] = new_entry
                save_state(state)
                changed = True
            else:
                reason = ui.last_error or 'unknown'
                print(f'{user}: 拉取未完成({reason}),状态未更新,下次将重试')
                if reason in ('rate_limit', 'auth'):
                    # 配额/认证是全局性失败,后续用户也拉不动,提前退出
                    break
                # 结构异常等个体性问题:该用户下次重试,继续处理其他用户
    finally:
        api.close()
    print('==== 增量拉取结束 ====')
    return changed


def _hint_alias(user):
    """封号/注销归档时提示同组替代账号(alias 展示层,不合并数据)"""
    group = next((g for g, ms in config.alias.items() if user in ms), None)
    if group:
        others = [m for m in config.alias[group] if m != user]
        print(f'提示: {user} 疑似属于别名组「{group}」,同组账号: {others or "(无)"}')


def _cmd_add(names):
    """add [user...]:加入名单(下次 sync 自动全量拉取);无参数则交互输入"""
    if not names:
        print('输入要追踪的用户名(@后面的字符),每行一个,空行结束:')
        while True:
            try:
                line = input().strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                break
            names.append(line)
    added = config.add_users(names)
    for n in added:
        print(f'已加入: {n}')
    if not added:
        print('没有新增(已在名单中或输入为空)')
    print('下次运行 sync_down.py 时会自动全量拉取新加入的用户,此后转入增量')


def _cmd_remove(names):
    removed = config.remove_users(names)
    for n in removed:
        print(f'已移除: {n}')
    if not removed:
        print('没有移除(不在名单中)')


def _norm_name(name):
    """昵称归一化:去 emoji/空白/括号及内容/标点,小写。用于疑似同人/换号识别(提示层,不自动合并)"""
    return re.sub(r'[()（）【】\[\]{}]|[^\w\u4e00-\u9fff]', '', str(name or '')).lower()


def _alias_candidates(users_with_names):
    """疑似同人候选:归一化昵称互为前缀(长度>=2)的两两组合。
    users_with_names: [(screen_name, display_name), ...] → [(a, b, 说明), ...]"""
    normed = [(u, n, _norm_name(n)) for u, n in users_with_names]
    cands = []
    for i in range(len(normed)):
        for j in range(i + 1, len(normed)):
            u1, n1, s1 = normed[i]
            u2, n2, s2 = normed[j]
            if not s1 or not s2:
                continue
            if len(s1) >= 2 and len(s2) >= 2 and (s1.startswith(s2) or s2.startswith(s1)):
                cands.append((u1, u2, f'昵称「{n1}」与「{n2}」相似'))
    return cands


def _archived_user_names():
    """从【已封号】归档目录的 CSV 首行提取昵称 → [(screen_name, display_name), ...]"""
    result = []
    if not os.path.isdir(config.save_path):
        return result
    for entry in os.listdir(config.save_path):
        if not entry.startswith('【已封号】'):
            continue
        screen = entry[len('【已封号】'):]
        screen = screen.split('_')[0]  # 时间戳后缀的归档名
        csv_files = [f for f in os.listdir(os.path.join(config.save_path, entry)) if f.endswith('.csv')]
        name = screen
        if csv_files:
            try:
                with open(os.path.join(config.save_path, entry, csv_files[0]), encoding='utf-8-sig') as f:
                    row = f.readline().strip()
                if row:
                    name = row.split(',')[0]
            except OSError:
                pass
        result.append((screen, name))
    return result


def _print_alias_candidates():
    """打印疑似同人/换号候选(仅提示,需人工用 alias 命令确认);已归组账号不参与"""
    state = load_state()
    known = [(u, (st or {}).get('name') or u) for u, st in ((u, state.get(u)) for u in config.user_list)]
    known += _archived_user_names()
    grouped = set(m for ms in config.alias.values() for m in ms)
    cands = _alias_candidates([(u, n) for u, n in known if u not in grouped])
    for a, b, why in cands:
        print(f'提示: 疑似同人/换号 —— {a} 与 {b}({why})。确认后用 `sync_down.py alias 组名 {a} {b}` 归组')


def _cmd_report():
    """内容去重报告:全库 md5 扫描,按 alias 组聚合重复内容(提示层,不自动删任何文件)"""
    report = build_dup_report(config.save_path, config.alias)
    print('==== 内容去重报告(md5 精确匹配) ====')
    print(f'媒体文件: {report["total"]},唯一内容: {report["unique"]},重复组: {report["dup_groups"]}')
    print(f'可节省空间(每组保留 1 份,其余删除): {report["savable_mb"]:.1f} MB')
    if not report['groups']:
        print('无重复内容')
        return
    for g in report['groups']:
        first = g['files'][0]
        print(f'  [{g["scope"]}] {g["md5"][:8]} x{len(g["files"])}: '
              f'{first[0]}/{os.path.basename(first[1])} 等')
    if report['alias_hits']:
        print('== 命中别名组 ==')
        for g in report['alias_hits']:
            print(f'  「{g}」: {report["alias_hits"][g]} 组重复(组内成员互发老图)')


def build_dup_report(root, alias):
    """全库 md5 扫描 → 结构化报告(纯逻辑,可测试)。
    alias: {组名: [成员...]}。返回 dict:total/unique/dup_groups/savable_mb/groups/alias_hits"""
    idx = defaultdict(list)
    total = 0
    for user in sorted(os.listdir(root)):
        udir = os.path.join(root, user)
        if not os.path.isdir(udir) or user.startswith('【已封号】'):
            continue
        for f in os.listdir(udir):
            if f.endswith('.csv'):
                continue
            path = os.path.join(udir, f)
            m = hashlib.md5()
            try:
                with open(path, 'rb') as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b''):
                        m.update(chunk)
            except OSError:
                continue
            total += 1
            idx[m.hexdigest()].append((user, f))

    groups = [{'md5': k, 'files': v} for k, v in idx.items() if len(v) > 1]
    savable = 0
    alias_member = {u: g for g, ms in (alias or {}).items() for u in ms}
    alias_hits = defaultdict(int)
    for g in groups:
        sizes = []
        for user, f in g['files']:
            try:
                sizes.append(os.path.getsize(os.path.join(root, user, f)))
            except OSError:
                sizes.append(0)
        savable += sum(sizes) - max(sizes) if sizes else 0
        users = {u for u, _ in g['files']}
        if len(users) == 1:
            g['scope'] = 'same_user'
        else:
            groups_of = {alias_member.get(u) for u in users}
            g['scope'] = 'alias_group' if len(groups_of) == 1 and None not in groups_of else 'cross'
            if g['scope'] == 'alias_group':
                alias_hits[groups_of.pop()] += 1
    return {'total': total, 'unique': total - len(groups), 'dup_groups': len(groups),
            'savable_mb': savable / 1024 / 1024, 'groups': groups,
            'alias_hits': dict(alias_hits)}


def _cmd_list():
    state = load_state()
    print('==== 追踪名单 ====')
    for u in config.user_list:
        st = state.get(u)
        if st:
            print(f'  {u}: rest_id={st.get("rest_id")}, latest_media_id={st.get("latest_media_id")}, 上次检查={st.get("checked_at")}')
        else:
            print(f'  {u}: 无状态 → 下次运行将全量拉取')
    if config.alias:
        print('==== 别名组 ====')
        for group, members in config.alias.items():
            print(f'  「{group}」: {members}')
    else:
        print('==== 别名组 ====(未配置,alias 组名 成员... 可添加)')


def _cmd_dedup(apply=False):
    """存量去重:同用户/同组内 md5 完全一致的内容保留时间戳最早一份。
    dry-run 打印计划;--apply 执行删除(仅删较晚副本,最早版本绝不动;cross 跨组不处理)"""
    report = build_dup_report(config.save_path, config.alias)
    plan = []
    for g in report['groups']:
        if g['scope'] == 'cross':
            continue
        keep = min(os.path.basename(f) for _, f in g['files'])  # 字典序 = 时间序
        plan += [(user, f) for user, f in g['files'] if os.path.basename(f) != keep]
    if not plan:
        print('无待清理的重复内容(same_user/alias_group 均无)')
        return
    if apply:
        removed = 0
        for user, f in plan:
            try:
                os.remove(os.path.join(config.save_path, user, f))
                removed += 1
            except OSError as e:
                print(f'删除失败 {user}/{f}: {e}')
        print(f'已删除 {removed} 个重复文件(每组保留时间戳最早版本)')
    else:
        print(f'计划删除 {len(plan)} 个重复文件(每组保留最早),确认后执行: sync_down.py dedup --apply')
        for user, f in plan[:30]:
            print(f'  {user}/{f}')
        if len(plan) > 30:
            print(f'  ... 其余 {len(plan) - 30} 个')


def _cmd_alias(group, members):
    if not group or not members:
        print('用法: sync_down.py alias 组名 成员1 成员2 ...')
        return
    saved = config.set_alias(group, members)
    print(f'别名组「{group}」: {saved}')


def _main_cli():
    parser = argparse.ArgumentParser(prog='sync_down', description='增量拉取(首次全量自动分派):无子命令时直接执行同步')
    sub = parser.add_subparsers(dest='cmd')
    p_add = sub.add_parser('add', help='加入追踪名单(新用户下次运行自动全量拉取)')
    p_add.add_argument('users', nargs='*')
    p_rm = sub.add_parser('remove', help='移出追踪名单')
    p_rm.add_argument('users', nargs='+')
    sub.add_parser('list', help='查看名单/别名组/状态摘要')
    p_alias = sub.add_parser('alias', help='设置别名组:alias 组名 成员1 成员2 ...')
    p_alias.add_argument('group')
    p_alias.add_argument('members', nargs='+')
    sub.add_parser('report', help='内容去重报告(md5 扫描,按别名组聚合;只报告不删文件)')
    sub.add_parser('sync', help='执行同步(默认,可省略)')
    p_dedup = sub.add_parser('dedup', help='存量去重:同用户/同组完全一致内容保留最早(默认 dry-run,--apply 执行)')
    p_dedup.add_argument('--apply', action='store_true', help='执行删除(默认仅打印计划)')
    args = parser.parse_args()
    if args.cmd == 'add':
        _cmd_add(args.users)
    elif args.cmd == 'remove':
        _cmd_remove(args.users)
    elif args.cmd == 'list':
        _cmd_list()
    elif args.cmd == 'alias':
        _cmd_alias(args.group, args.members)
    elif args.cmd == 'report':
        _cmd_report()
    elif args.cmd == 'dedup':
        _cmd_dedup(args.apply)
    else:  # 无参数或 sync
        sync()


if __name__ == '__main__':
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    _main_cli()
