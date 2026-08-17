# gcTwitterDL

推特图片、视频、文本下载器。以用户名为参数,爬取该用户推文中的媒体内容,支持增量拉取、按 Tag 搜索、评论区下载、封号自动归档。

> 本仓库是 upstream [`caolvchong-top/twitter_download`](https://github.com/caolvchong-top/twitter_download) 的自用 fork,独立维护发布。

## 特性

- 主入口 `main.py`:按 `settings.json` 下载指定用户的图片/视频/文本,支持排除转推、时间范围限制、Highlights、Likes
- 增量拉取 `sync_down.py`:不遍历式全量拉取,每个用户每次只做 1 次轻量 API 调用
- 封号自动归档:检测到封号/注销,自动把下载目录重命名为 `【已封号】用户名`,清理下载日志
- 交互式控制台(Windows):双击 `run_cli.bat`,菜单里就能增量拉取、添加/移除用户、看去重报告
- 独立脚本:`tag_down.py`(按 Tag/高级搜索)、`reply_down.py`(评论区)、`text_down.py`(纯文本 CSV)、`profile_down.py`(头像/横幅/简介)
- 媒体文件名 `{时间戳}-{推文ID}-img/vid{图序号}`,多图可归组,不受下载顺序影响
- 内容去重:同用户/别名组内 md5 全局去重,保留最早一份

## 安装

Python 版本须 >= 3.8。

```bash
git clone https://github.com/GenCurtis/gcTwitterDL.git
cd gcTwitterDL
pip install -r requirements.txt   # 版本已锁定(httpx==0.28.1),不要盲目升级
```

## 配置

1. 从模板复制出真实配置(都已在 .gitignore 中,不会入库):
   - `settings.json` ← `settings.template.json`
   - `users.json` ← `users.template.json`(用户名单 + 别名组)
2. cookie 需要 **auth_token 和 ct0** 两个字段(分号结尾)。ct0 用来生成 `x-csrf-token` 请求头,缺了所有 API 请求都会失败。

`settings.json` 要点:

- `save_path`:支持 Windows 反斜杠路径,如 `C:\your_path\gcTwitterDL\downloads`;留空默认 `<仓库根>/downloads`。JSON 里反斜杠要写成 `\\`,手抄成单个 `\` 导致解析失败时,程序会自动容错修复。
- `user_lst`:逗号分隔 `"a,b,c"` / 换行分隔 / JSON 数组 `["a", "b", "c"]` 三种写法均可。日常用 `sync_down.py` 的 `add/remove/alias` 命令维护也行。

## 运行

```bash
python main.py          # 下载 settings.json 中配置的用户(全量/增量自动判断)
python sync_down.py     # 增量拉取:只拉有变化的用户
```

Windows 交互式控制台:双击根目录 `run_cli.bat` 进入菜单,等效命令 `python sync_down.py menu`。

其他入口脚本:

```bash
python scripts/tag_down.py
python scripts/reply_down.py
python scripts/text_down.py
python scripts/profile_down.py
```

## 增量拉取原理

`sync_down.py` 不遍历式全量拉取。对名单里每个用户只做 1 次轻量 API 调用(`UserMedia` 第一页,rest_id 缓存在状态文件里),取最新媒体推文 ID(snowflake,随时间单调递增),和 `downloads/_sync_state.json` 里上次的值对比:

- 相同 → 无新内容,跳过,不消耗配额
- 变大 → 有更新,进入 main.py 增量流程,只拉新内容
- 封号/注销(`UserUnavailable`/`Tombstone`)→ 自动归档到 `【已封号】用户名`,清掉目录里的 csv / cache_data.log,媒体文件和 md 保留
- 拉取中断(配额耗尽等)→ 状态不更新,下次自动重试

ID 对比比"推文数量"可靠:用户删一条发一条时数量不变,ID 必然变大,照样能侦测到;删帖只会让 ID 回退,判定为无新内容,不会丢内容,也不会白跑一遍。

定时运行(每半天,Windows 计划任务):

```
schtasks /create /tn TwitterSync /tr "python C:\your_path\gcTwitterDL\sync_down.py" /sc HOURLY /mo 12
```

## 按 Tag 下载 & 高级搜索

`scripts/tag_down.py` 顶部配置:

```python
tag = '#ヨルクラ'   # 带 # 号,可留空
_filter = ""        # 高级搜索:在 https://x.com/search-advanced 组装条件后填入
```

- tag 留空时,以 `_filter` 的内容作为文件夹名称
- `_filter` 里所有双引号要改成单引号或加转义,例如 `"Monika"` → `'Monika'`

## 已知限制

- **API 每日配额**:GraphQL 调用约消耗「总推数(含转推) / 19」次,媒体下载不计入次数。抛出 `Rate limit exceeded` 就是当日配额耗尽,排除转推能大幅减少消耗。
- **非官方接口,随时可能失效**:每个接口的 GraphQL query id 硬编码在代码里,失效时需从 x.com 网页端抓取最新值。
- `tag_down.py` / `reply_down.py` 需要 `X-Client-Transaction-ID`(由 `transaction_generate.py` 生成),偶尔返回无效,重跑一次即可。
- Likes 模式不支持时间范围限制。

## 效果预览

<details>
<summary>展开查看</summary>

**主下载(main.py)效果**

![main](https://github.com/caolvchong-top/twitter_download/assets/57820488/39da9658-f40f-40d6-8480-9dff850076da)

**评论区下载(reply_down.py)**

![reply](https://github.com/user-attachments/assets/43708c8f-528d-4000-bf45-409a53ee3bc7)

**按 Tag 获取(tag_down.py)**

![tag](https://github.com/caolvchong-top/twitter_download/assets/57820488/aa109e18-5ef1-4d77-902c-658ed1b3ff53)

**纯文本推文(text_down.py)**

![text](https://github.com/caolvchong-top/twitter_download/assets/57820488/0998b6b1-c313-4b1d-a78e-525a666098b2)

**图片下载效果**

![img](https://github.com/caolvchong-top/twitter_download/assets/57820488/736f7554-612b-4bec-8baf-4a5ab45c6e04)

**视频下载效果**

![vid](https://github.com/caolvchong-top/twitter_download/assets/57820488/6f732042-6f96-4e7a-bd16-e7d08a46a90e)

**CSV 统计**

![csv](https://github.com/caolvchong-top/twitter_download/assets/57820488/b5dfc741-e10f-409a-b298-d56ea236bc5f)

</details>

> 图片都是老版本的效果,仅作参考。

## 仓库结构

```
main.py         主入口:按 settings.json 下载指定用户的媒体(含转推/Highlights/Likes)
sync_down.py    增量拉取 + 用户名单/别名组管理 + 交互式菜单
scripts/        tag_down / reply_down / text_down / profile_down / transaction_generate
tw_dl/          公共包:api / downloader / config / csv_writer / md_writer / cache / archive / dedup / utils / logger
tests/          pytest 纯逻辑测试(无网络):python -m pytest tests
settings.template.json / users.template.json   配置模板(复制为真实配置后填写)
```

## 免责声明

**EN**

1. This project is strictly for programming learning, academic research, and personal practice.
2. The intellectual property of all media content (images, videos, etc.) downloaded using this tool belongs to the original authors and the respective platforms. Please respect relevant copyrights.
3. Users must comply with applicable laws, the target platform's Terms of Service, and relevant copyright regulations. Do not use this tool for malicious scraping, copyright infringement, illegal distribution, or other unlawful activities.
4. The developer assumes no responsibility for any violations, legal disputes, or direct/indirect losses caused by the improper use of this tool. Use at your own risk.

**ZH**

1. 本项目仅供编程学习交流、学术研究及个人练习使用。
2. 使用本工具下载的所有媒体内容(图片、视频等)的知识产权均归原作者及所属平台所有,请尊重相关版权。
3. 请勿将本工具及所获取的数据用于恶意抓取、侵权传播或其他违法用途。
4. 开发者不对任何因不当使用本工具而导致的违规行为、法律纠纷或直接/间接损失承担责任。请风险自担。

## 上游

fork 自 [`caolvchong-top/twitter_download`](https://github.com/caolvchong-top/twitter_download),感谢原作者的工作。合并上游新改动时只采用 squash 合并,发布历史保持单提交。
