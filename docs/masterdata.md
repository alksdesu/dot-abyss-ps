# 主数据接入与版本更新

[文档目录](README.md) · [资源索引](assets.md)

PC 端使用客户端 `DownloadCache` 中的原始 MessagePack 主数据。首次部署直接运行 [PC 首次启动](first-start.md) 中的 `setup-pc.ps1` 即可自动查找缓存、校验 schema 并激活。以下说明供日常开发与版本更新维护使用。

## 1. 检查、暂存与激活

主数据同时绑定包名、客户端版本、metadata SHA-256 与 schema SHA-256（对应关系见 [客户端支持](../changelog.md#客户端支持)）。

先在仓库根目录 PowerShell 中加载 [维护命令参数](../changelog.md#维护命令参数) 变量块，再运行：

```powershell
.\.venv\Scripts\python.exe -m dotabyss_ps.masterdata inspect --payload '<主数据.dat>' --schema $schemaPath
.\.venv\Scripts\python.exe -m dotabyss_ps.masterdata --data-dir $dataDirectory stage --payload '<主数据.dat>' --schema $schemaPath --source 'PC 本地缓存'
.\.venv\Scripts\python.exe -m dotabyss_ps.masterdata --data-dir $dataDirectory activate '<stage 返回的 revision>'
```

- `stage`：校验表名、列顺序、字段类型与主键，将不可变文件保存至 `master/blobs/<sha256>.msgpack` 并返回 `local-...` 格式的 revision。
- `activate`：在 SQLite 事务中切换当前活动数据集并同步更新 `resource_version`。

## 2. 版本清单维护与热更新

所有版本、结构与路径定义集中维护在 [pc/releases/manifest.json](../pc/releases/manifest.json) 中：

- `build`：定义客户端二进制指纹、schema、隔离标识与资源路径协议。
- `content`：记录主数据、catalog 与缓存种子信息。
- `paths`：定义默认安装与数据目录路径。

修改 `manifest.json` 后，在仓库根目录运行以下命令自动同步旧格式投影与 C# 结构常量：

```powershell
.\.venv\Scripts\python.exe -m tools.generate_release_bindings
.\.venv\Scripts\python.exe -m tools.generate_release_bindings --check
```

当游戏仅更新内容（新增角色、活动、剧情、素材）而客户端二进制结构未变时，只需更新 `content` 并重新导入主数据与资源，安装器会自动跳过 C# 插件重编译。

## 3. HTTP 接口

- `/local/master`：返回当前激活主数据的元信息。
- `/local/master/<revision>/first.msgpack`：用于诊断读取。
- `/data/<revision>`：客户端原生主数据下载端点（支持 SHA-256 ETag 与 `304 Not Modified`）。
