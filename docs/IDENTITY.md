# 影片识别修复

[中文](IDENTITY.md) | [English](IDENTITY.en.md)

管理中心的「媒体识别」使用已配置的 Emby 地址与 API Key，第一版支持配置输出目录内的电影 STRM。无需另外安装 Emby 插件、运行服务或填写 TMDB 密钥。

## 使用

1. 刷新影片列表。「未识别」表示缺少 TMDB/IMDb/TVDB 身份；缺少海报或简介有独立的筛选范围，并不等同于未识别。
2. 点击「搜索影片及海报」打开候选弹窗，片名明确时自动搜索；年份或 ID 冲突会先提示核对。可改用目录标题、手动输入片名或填写 TMDB ID。
3. 比较候选海报、片名、年份与简介，系统不会自动采用第一条。海报失败显示重试入口，候选过期需重新搜索；提供器未返回的简介会标记暂无。
4. 点击「确认匹配此影片」并确认。按需勾选替换已有图片；默认保留已有图片。Emby 执行自己的识别与刷新操作。
5. 处理记录会回读核对影片 ID、标题、海报及简介。超时、网络异常或字段未补齐不会显示为全部成功；可重新核对，也可在 Emby 中刷新。

已有 ID 但认错影片的内容在「全部影片」中查找。搜索列表支持片名、原路径、Emby 条目编号。

关闭弹窗不会撤销已提交的操作。提交超时且身份原本就相同，不以旧信息推断刷新完成；请求替换已有海报时会核对图片标记。标记不变会保留为未验证，重新下载相同图片也可能不改变标记。

## 保留与恢复

- 不改名、不移动、不删除 STRM，不下载网盘视频；候选查询不产生网盘目录扫描。播放取链仍使用 STRM 原内容。
- 私有 SQLite 记录位于 `data/identity/identity.sqlite3`，包含服务器身份、原 STRM 路径、内容指纹、确认的候选、原身份和提交记录。备份时应与其他 data 一起备份，不应提交到 Git。
- Emby 重启后提交记录仍可回读。原路径及内容相同、仅条目 ID 因重建变化时，列表显示已确认绑定；用户可选择「使用已确认的绑定搜索」再确认恢复。
- 路径变更、内容改变、切换 Emby 服务器不会自动套用旧绑定。本版没有无人确认批量应用、自动重命名、NFO 生成或剧集季集重排。
- 不直接修改 Emby 数据库和用户播放记录。原生识别可能影响基于 provider ID 的版本关联和观看状态；上线前应对自己的媒体库验证。

## 一致性与接口

- 候选令牌在服务端保存，30 分钟过期，与服务器、条目、已有身份及 STRM 内容绑定。浏览器不能提交任意候选对象来写入。
- 同一候选重复提交返回同一处理记录；同一影片有待核对提交时阻止第二个不同候选。
- 应用身份与扫描使用同一个内核文件锁。扫描写入期间返回可理解的提示，不中断扫描。
- 确认写入前持久化记录。提交响应异常时先核对实际结果，不盲目重放请求。
- API 位于 `/api/admin/xstrm/identity/`：GET `items?scope=unmatched|incomplete|all`、`history`、`operation?id=...`、`image?id=...`；POST `search`、`apply`。沿用管理入口 Basic Auth 与写请求校验头。
- 候选图片由后端使用不透明令牌经 Emby 代理，浏览器不接触 Emby API Key 或上游图片地址。认证请求不跟随 HTTP 重定向，避免密钥跨主机传送。

参考：[Emby Identify](https://emby.media/support/articles/Identify.html)、[候选搜索](https://dev.emby.media/reference/RestAPI/ItemLookupService/postItemsRemotesearchMovie.html)、[应用识别](https://dev.emby.media/reference/RestAPI/ItemLookupService/postItemsRemotesearchApplyById.html)。
