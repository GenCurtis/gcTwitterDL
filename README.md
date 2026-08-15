# 推特图片下载   &nbsp; (๑¯◡¯๑) 
推特 图片 & 视频 & 文本 下载，以用户名为参数，爬取该用户推文中的图片与视频(含gif)

支持排除转推内容 & 多用户爬取 & 时间范围限制 & 按Tag获取 & 纯文本获取 & 高级搜索 & 评论区下载
& 增量拉取 & 封号自动归档(自用 fork 新增)

--- 
## Disclaimer / 免责声明

> **EN**
> 
> 1. This project is strictly for programming learning, academic research, and personal practice.
> 
> 2. The intellectual property of all media content (images, videos, etc.) downloaded using this tool belongs to the original authors and the respective platforms. Please respect relevant copyrights.
> 
> 3. Users must comply with applicable laws, the target platform's Terms of Service, and relevant copyright regulations. Do not use this tool for malicious scraping, copyright infringement, illegal distribution, or other unlawful activities.
> 
> 4. The developer assumes no responsibility for any violations, legal disputes, or direct/indirect losses caused by the improper use of this tool. Use at your own risk.
> 

<br>

> **ZH**
> 
> 1. 本项目仅供编程学习交流、学术研究及个人练习使用。
> 
> 2. 使用本工具下载的所有媒体内容（图片、视频等）的知识产权均归原作者及所属平台所有，请尊重相关版权。
> 
> 3. 请勿将本工具及所获取的数据用于恶意抓取、侵权传播或其他违法用途。
> 
> 4. 开发者不对任何因不当使用本工具而导致的违规行为、法律纠纷或直接/间接损失承担责任。请风险自担。
> 
---
**目前老马加了API的请求次数限制** 
``` 
当程序抛出：Rate limit exceeded 
即表示该账号当日的API调用次数已耗尽

if 选择包含转推:
  爬完一个用户需要调用的API次数约为:总推数(含转推) / 19
elif 不包含:
  会大大减少API调用次数

下载不计入次数 
```

# Change Log 
* **2026-08-15 (自用 fork)** 
  * 全面重构为 `tw_dl/` 公共包架构(配置/日志/API客户端/下载器/CSV/MD/缓存收口),修复多个下载 bug 
  * 新增 `sync_down.py` 增量拉取:最新媒体推文 ID 侦测,不遍历式全量拉取 
  * 封号自动侦测与归档:重命名「【已封号】用户名」并清理下载日志 
  * 目录整理:独立入口脚本归档到 `scripts/` 
  * `settings.json` 支持 Windows 反斜杠路径、`user_lst` 支持数组/换行 
  * 后续改动以 git 提交历史为准(本文件 Change Log 只保留上游记录)

* **2025-08-09** 
  * 支持获取用户主页内容(头像&banner&简介)--**请直接配置profile_down.py文件并运行**

* **2025-04-26** 
  * 替换部分失效接口 
  * `tag_down reply_down`增加`X-Client-Transaction-ID`校验, 请重新运行`pip install -r requirements.txt`安装依赖 
  * // 目前生成的`transaction-id`仍有小概率失效, 当程序抛出`获取数据失败`时可以尝试重新运行 
  * 目前`main text_down`似乎未受`X-Client-Transaction-ID`校验影响 
  * Reference: `https://github.com/iSarabjitDhiman/XClientTransaction`

* **2025-03-03** 
  * 支持下载评论区(指定用户或推文链接)--**请直接配置reply_down.py文件并运行**

* **2024-05-24** 
  * 按Tag获取支持保存文本内容 

* **2024-05-11**
  * 支持获取纯文本推文--**请直接配置text_down.py文件并运行**
    
    // (下方有预览) 注意，此功能会大量消耗API次数(参考上方公式)，默认排除转推内容
* **2024-05-10**
  * 支持按Tag获取--**请直接配置tag_down.py文件并运行**
  
    // 保存格式 (下方有预览)：. / {#Tag} / {datetime} \_ {@username} \_ { md5( media_url )[:4] } . { png / mp4 }

* **2024-03-09**
  * 支持记录已下载内容,避免重复下载 (如有问题请发issue)
  * 支持自动同步最新内容
* **2024-01-16**
  * 适配 [ **喜欢(Likes)** ] 标签页 
* **2024-01-10**
  * 新增统计数据 [ **Favorite, Retweet, Reply** ]
* **2024-01-05**
  * 适配Twieer新标签页 [ **亮点(HighLights)** ]
* **2023-12-12**
  * 适配Twitter新API
* **2023-10-12**
  * 添加 生成爬取信息 功能
* **2023-10-06**
  * 添加 时间范围限制 功能
  * 统一文件保存格式
    * 文件夹：用户id (@后面的)
    * 文件：推文日期-[img/vid]_下载计数.文件后缀
      
* **2023-09-15**
  * 添加 视频下载 功能
 
---

<div align="center"> 

| ![e53923662b627a645fcd2b0b3feadb3b](https://github.com/caolvchong-top/twitter_download/assets/57820488/39da9658-f40f-40d6-8480-9dff850076da) |
|:--:| 
| **(๑´ڡ`๑)** | 

</div>

部署
--- 

**Linux** : 
``` 
git clone https://github.com/GenCurtis/gcTwitterDL.git 
cd gcTwitterDL 
pip3 install -r requirements.txt

#Python版本须>=3.8  httpx==0.28.1
``` 
**运行** : 
``` 
从 settings.template.json / users.template.json 复制出 settings.json / users.json 再配置
(settings.json 含真实 cookie、users.json 为用户名单,均不入库;模板内只有占位符)
python main.py              # 下载 settings.json 中的用户(增量/全量由 autoSync 决定)
python sync_down.py         # 增量拉取:只拉有变化的用户(见下) — 自用 fork 新增
``` 
**Windows** 和上面的一样，配置完settings.json后运行main.py即可

其他入口脚本在 `scripts/` 下,运行方式不变:

``` 
python scripts/tag_down.py
python scripts/reply_down.py
python scripts/text_down.py
python scripts/profile_down.py
```

> 本仓库是 upstream `caolvchong-top/twitter_download` 的自用 fork,独立维护发布。

仓库结构
---
```
main.py            主入口:按 settings.json 下载指定用户的媒体(含转推/亮点/点赞标签)
sync_down.py       增量拉取:仅对变化用户拉新内容(状态文件驱动);封号自动归档;
                   命令行 add/remove/list/alias 管理用户名单与别名组
scripts/           tag_down(按标签/高级搜索) / reply_down(评论) / text_down(纯文本CSV)
                   / profile_down(头像/横幅/简介) / transaction_generate(事务ID生成)
tw_dl/             公共包:api(请求/重试/限流) / downloader(并发下载/内容去重)
                   / config(settings 解析) / csv_writer / md_writer / cache(下载日志)
                   / archive(封号归档) / dedup(md5 全局去重) / utils / logger
tests/             pytest 纯逻辑测试(无网络):python -m pytest tests
settings.template.json / users.template.json   配置模板(复制为真实配置后填写,均不入库)
```

> 备注:上游合并/审计等内部维护记录为本地私有文档(AGENTS.md 等),不随仓库发布。

增量拉取(sync_down.py)
---
自用 fork 新增:**不遍历式全量拉取**。每次运行对列表内每个用户只做 1 次轻量 API 调用
(`UserMedia` 第一页,借助缓存在状态文件里的 rest_id),取**最新媒体推文 ID**
(snowflake,随时间单调递增),与 `downloads/_sync_state.json` 记录的上次值对比:

- 相同 → 无新内容,跳过(不消耗多余配额)
- 不同 → 进入 main.py 的增量流程(autoSync 基于本地文件设定起点,只拉新内容)
- 被封号(`UserUnavailable`/`Tombstone`)→ 自动把 `downloads/{用户名}` 归档重命名为
  `【已封号】{用户名}`,并清理目录内的 csv / cache_data.log 下载日志(媒体文件与 md 保留)
- 拉取中断(配额耗尽等)→ 状态不更新,下次自动重试

ID 对比比"推文数量"可靠:用户删一条发一条时数量不变但 ID 必然变大(仍能侦测到);
删帖只会让 ID 回退,与上次相同或更小都判定为「无新内容」,绝不丢内容。

定时运行(每半天,Windows 计划任务):
``` 
schtasks /create /tn TwitterSync /tr "python C:\your_path\gcTwitterDL\sync_down.py" /sc HOURLY /mo 12
```

配置格式说明(settings.json)
---
- `save_path`:支持 Windows 常规路径(反斜杠),如 `C:\your_path\gcTwitterDL\downloads`;
  留空时默认使用 `<仓库根>/downloads`。JSON 中反斜杠需写成 `\\`,若手抄成单个 `\` 导致 JSON
  解析失败,程序会自动容错修复(将裸反斜杠替换为正斜杠)。
- `user_lst`:三种写法均可 — 逗号分隔 `"a,b,c"` / 换行分隔(JSON 中写 `\n`)/ JSON 数组
  `["a", "b", "c"]`。成百上千用户时建议用数组,便于排版。


注意事项
---

**按Tag下载&高级搜索 --> scripts/tag_down.py** 

**下载评论区 --> scripts/reply_down.py** 

**指定用户纯文本推文获取 --> scripts/text_down.py** 

**指定用户媒体文件获取&转推&亮点&喜欢(只能本人账号)等 --> main.py + settings.json** 

**增量拉取/封号自动归档 --> sync_down.py** 

其余各种不能解决的需求建议试试tag_down的高级搜索, 或是提交Issue 


Tag_Down 功能扩展 (高级搜索) &nbsp;&nbsp; <sub>//万金油</sub> 
---
~~其实按功能应该叫`search_down`~~

对于部分主程序难以实现的需求可以尝试配置`tag_down.py`的`filter`来曲线解决: 

|部分例子|
|:--:|
|大批量下载 -> 分批下载|
|指定时间范围|
|各类关键词搜索/排除|
|指定/排除目标用户|
|指定大于互动量的推文|
|指定推文语言|
|......| 

``` 
// 配置

tag = '#ヨルクラ'
# 填入tag 带上#号 可留空
_filter = ""
# (可选项) 高级搜索
# 请在 https://x.com/search-advanced 中组装搜索条件，复制搜索栏的内容填入_filter
# 注意，_filter中所有出现的双引号都需要改为单引号或添加转义符 例如 "Monika" -> 'Monika'

# 当tag选项留空时，将尝试以_filter的内容作为文件夹名称
``` 
推特高级搜索：https://x.com/search-advanced 

实例参考：https://github.com/caolvchong-top/twitter_download/issues/63#issuecomment-2351039320 & https://github.com/caolvchong-top/twitter_download/issues/106


效果预览
---
![20230720134231](https://github.com/caolvchong-top/twitter_download/assets/57820488/ee6a1c13-2b0c-47e9-a260-1ac529bec678) 


**↑↑老版本的图，仅效果参考**


![20230720134253](https://github.com/caolvchong-top/twitter_download/assets/57820488/6e5ba42f-2dc4-4fa1-8cf6-152246378756)


**评论区下载 Reply_down.py** 

![asehniubnsiebfi](https://github.com/user-attachments/assets/43708c8f-528d-4000-bf45-409a53ee3bc7)

 
**按Tag获取 Tag_down.py** 

![image](https://github.com/caolvchong-top/twitter_download/assets/57820488/aa109e18-5ef1-4d77-902c-658ed1b3ff53)

**纯文本推文获取(仅文本) Text_down.py** 

![QQ截图20240511032859](https://github.com/caolvchong-top/twitter_download/assets/57820488/0998b6b1-c313-4b1d-a78e-525a666098b2)



**图片下载效果**

![test1](https://github.com/caolvchong-top/twitter_download/assets/57820488/736f7554-612b-4bec-8baf-4a5ab45c6e04)


**视频下载效果**

![test2](https://github.com/caolvchong-top/twitter_download/assets/57820488/6f732042-6f96-4e7a-bd16-e7d08a46a90e)



**生成CSV统计**

![屏幕截图 2023-10-12 223755](https://github.com/caolvchong-top/twitter_download/assets/57820488/b5dfc741-e10f-409a-b298-d56ea236bc5f)



