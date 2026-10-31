# 主数据接入与版本更新

[文档目录](README.md) · [资源索引](assets.md)

PC 使用客户端 `DownloadCache` 中的主数据，保留原始 MessagePack 字节。首次部署优先使用 [PC 首次启动](first-start.md) 中的初始化脚本，自动寻找匹配缓存、检查 schema 并完成导入。下列命令用于开发和维护，不需要在普通首装时重复执行。

## 客户端与结构绑定

主数据同时绑定包名、版本、metadata SHA-256 和 schema SHA-256。当前结构描述与客户端对应关系见 [适配记录](../changelog.md#客户端支持)。仓库保留的 Play、FANZA schema 用于各自客户端的协议兼容，不能因版本号相同就互换数据。

检查包括表名、列顺序、字段类型、整数范围和有证据支持的唯一键。额外表只有在 schema 明确允许原生 `Skip` 行为时保留；短行只有在明确记录末列默认规则时接受。视图中没有唯一性依据的重复 ID 会报告，不擅自删除。

`format_validated=true` 表示通过结构检查；`business_validated=false` 不表示数据一定不可用，也不能据此宣称所有玩法已验收。实际玩法兼容需要结合接口、客户端和资源验证。

## 检查、暂存与激活

先在项目根目录的 PowerShell 中执行 [维护命令参数](../changelog.md#维护命令参数) 的变量块，再在同一窗口执行以下命令，替换实际主数据路径。已有自定义安装应将 `$dataDirectory` 换成其实际目录：

```powershell
.\.venv\Scripts\python.exe -m dotabyss_ps.masterdata inspect --payload '<主数据.dat>' --schema $schemaPath
.\.venv\Scripts\python.exe -m dotabyss_ps.masterdata --data-dir $dataDirectory stage --payload '<主数据.dat>' --schema $schemaPath --source 'PC 本地缓存'
.\.venv\Scripts\python.exe -m dotabyss_ps.masterdata --data-dir $dataDirectory activate '<stage 返回的 revision>'
```

`stage` 校验并保存不可变 blob 与来源记录，不切换活动版本。revision 由 payload 与 schema 的 SHA-256 派生，格式为 `local-...`，每次使用当次返回值，不照抄旧文档中的版本号。

`activate` 复验 blob，在 SQLite 事务中更新活动数据集与 `resource_version`。文件保存在数据目录的 `master/blobs/<sha256>.msgpack`，元信息位于 `master_datasets`。运行版本必须与活动数据集一致，不能通过 `/local/runtime` 任意改写。

## 更新与回退

版本定义只维护 [manifest.json](../pc/releases/manifest.json)。`build` 包含客户端文件、schema、隔离身份和资源协议；`content` 包含主数据、catalog 及缓存种子；`paths` 给出当前安装的默认路径。历史 Android 支持项与经审查的补充表字段也在同一清单中。

Python 入口直接解析清单。兼容旧工具的 release 示例由生成器输出，C# 结构常量在插件构建前自动生成，不再手工改多份版本号或哈希。在仓库根目录更新清单后执行：

```powershell
.\.venv\Scripts\python.exe -m tools.generate_release_bindings
.\.venv\Scripts\python.exe -m tools.generate_release_bindings --check
```

仅增加角色、活动、剧情和素材，且字段布局与客户端二进制保持一致时，更新 `content` 并重新导入。插件启动时核对活动主数据、schema、资源清单和实际 catalog hash 响应的关联，不固定绑定某一次内容哈希。补充表继续检查字段数、类型和整数范围，新字段或未知玩法仍需单独适配。

安装器会记录源码、结构定义、schema、core/interop 和已安装 DLL 的指纹。已有匹配记录时，内容更新跳过插件构建；记录缺失、插件损坏或构建输入变化时重新编译。第一次升级到这套机制需要重新安装插件，并重启服务。

激活主数据本身不迁移已有存档，也不替换资源。更新前备份，并核对目标 schema、玩法字段、资源 manifest 与存档迁移需求。`setup-pc.ps1` 遇到已有其他主数据版本会拒绝覆盖；独立验证新版本应使用另一个数据目录和端口。

当前启动器按清单的默认结构选择 schema，不会从旧数据目录自动推断另一客户端版本。更换默认结构前必须明确处理旧安装和存档；内容可复用插件不等于旧存档可以跨主数据直接使用。

回退可激活已暂存的旧 revision，但还必须恢复匹配的资源与存档。保留旧 blob 不代表新存档可以直接交给旧服务端。存档兼容规则见[新档与旧档兼容](newgame-policy.md)，资源绑定规则见[资源说明](assets.md)。

导出新版本 schema 需要该客户端的模型声明和原生 formatter 依据。[export_master_schema.py](../tools/export_master_schema.py) 面向携带特定 interop 布局的 Android 解包目录，不能直接用于 PC 安装目录；不要把它当作通用的 PC 更新命令。

## HTTP 与缓存

- `/local/master` 返回活动主数据的元信息。
- `/local/master/<revision>/first.msgpack` 用于诊断读取。
- `/data/<revision>` 对应原生主数据下载路径。

服务端先读取并校验完整字节快照，再从同一快照生成正文和 SHA-256 ETag。未知 revision、损坏或截断文件明确失败，合法条件请求可返回 304。活动复刻等派生视图使用独立版本，原始 blob 保持不变。

本地适配插件保留原生请求路径，并改写到本机 origin 与端口。原生磁盘缓存名由环境和 revision 计算，因此只复制旧 `.dat` 文件名不能替代主数据导入或版本切换。
