# PC 首次启动

[文档目录](README.md) · [启动器与控制台](../console/README.md)

适用于 Windows PC 客户端。按 [适配记录](../changelog.md) 准备匹配的游戏、已下载资源、Python 和 .NET SDK。命令在仓库根目录执行；示例中的 `D:\dot\dotabyss_x_cl` 换成自己的原版游戏目录。

## 1. 初始化客户端和资源

```powershell
.\setup-pc.ps1 -Source 'D:\dot\dotabyss_x_cl'
```

脚本会创建 Python 环境、安装服务端依赖，然后：

- 校验游戏版本，准备到仓库相邻的 `dotabyss_pc/local-client`，保留原版目录。
- 生成本机 release 配置，自动填写缓存来源和当前用户的隔离目录。
- 按内容 SHA-256 查找对应版本的 catalog、hash 和主数据，缓存编号不同也能匹配。
- 解码 catalog 生成资源索引，校验并导入主数据、资源，使用返回的版本号激活。
- 如果加载器和 interop 已准备好，直接编译并安装私服插件。

无需复制或编辑 `pc/config.json`、替换 `YourName`、手抄 revision，也无需自己制作 `resource-url-index.json`。插件使用的 `pc-local.json` 会在启动器第一次启动游戏时自动创建；服务地址和存档标识随所选存档写入。

资源索引和缺失清单保存在所选数据目录的 `setup/` 中，默认目录见 [维护命令参数](../changelog.md#维护命令参数)。脚本不会创建角色存档、重置已有存档或自动迁移到另一主数据版本。

### 缓存位置

自动查找顺序：游戏目录旁的 `resource-cache`，当前 Windows 用户的原版游戏缓存，已有的隔离缓存。前两项结构示例：

```text
D:\dot\
  dotabyss_x_cl\
    ドットアビスX.exe
    ドットアビスX_Data\Caches\...
  resource-cache\
    com.unity.addressables\...
    DownloadCache\...
```

没有 `resource-cache` 时，会查找 `%USERPROFILE%\AppData\LocalLow\EXNOA LLC_\ドットアビスX`。其他位置可以明确指定：

```powershell
.\setup-pc.ps1 -Source 'D:\dot\dotabyss_x_cl' -CacheDirectory 'D:\cache\resource-cache' -SharedDirectory 'D:\cache\Shared'
```

`-CacheDirectory` 是包含 `com.unity.addressables`、`DownloadCache` 的目录。`-SharedDirectory` 是直接包含资源缓存桶的目录，名称可以是 `Shared`，也可以是 PC 游戏的 `ドットアビスX_Data\Caches`；不用移动或改名。

如果只想检查来源和索引，不写客户端或数据目录，添加 `-Check`。这不代表所有素材内容已经完成校验；完整校验发生在导入时。PowerShell 入口仍会准备缺少的 Python 环境。

资源不齐时默认不改变已激活的版本，并输出缺失清单。确认接受这些素材暂不可用后，使用相同命令加 `-AllowPartial`。损坏文件不会被当作“缺失”忽略；完全没有匹配素材时也不会激活。补齐文件后可重跑命令。

## 2. 首次准备加载器

如果脚本返回 `ready: false` 并提示缺少 interop，请在生成的 `dotabyss_pc/local-client` 中安装 BepInEx IL2CPP Windows x64。已验证的构建号与下载入口见 [运行与构建环境](../changelog.md#运行与构建环境)；两个运行库补丁的核对方法见 [兼容说明](../third_party/Il2CppInterop/COMPATIBILITY.md)。

解压后，加载器文件应与 `ドットアビスX.exe` 同级。启动该副本一次，让 BepInEx 生成 `BepInEx/interop/Project.dll`，随后退出游戏。不需要登录原版账号，也不要在这一步创建正式存档。首次生成的诊断日志是 `BepInEx/LogOutput.log`。

已有匹配 interop 的环境可以跳过生成过程。不要仅凭一条 `Class::Init` 警告断定必须等待上游更新；若生成失败或进程退出，应检查日志中的实际异常，并核对加载器、interop 与运行库版本。

## 3. 编译插件并打开启动器

```powershell
.\setup-pc.ps1 -PluginOnly
.\start-console.ps1 -Port 18083
```

插件直接引用客户端现有的 core 和 interop 编译，结构常量从统一版本清单自动生成，不需要把 BepInEx 再复制到 `toolchain/runtime`。安装前必须退出游戏；已有插件会备份到 `artifacts/setup/`。构建输入与已安装 DLL 的指纹均未变化时跳过编译；仅更新游戏内容不会使构建记录失效。没有改变时不重复生成备份。

启动器打开后，点击“启动服务”，新建或选择存档，再点击“启动游戏”。未显式指定数据目录时可能沿用已有启动器设置，首次使用才采用默认目录。若指向其他环境，先按 [维护命令参数](../changelog.md#维护命令参数) 核对 `$dataDirectory`，再加 `-DataDirectory $dataDirectory` 重新打开。

繁体翻译可通过启动器的“一键安装”配置，来源及许可见[翻译说明](../pc-translation/README.md)。

## 已按旧文档准备到一半

退出本地游戏，重跑第 1 步即可。已有客户端会先验证，已有配置保留；相同且完整的资源会复验后复用。已经手动导入的 catalog 若未绑定 PC 请求路径，会重新生成正确映射。已有服务需重启才能加载新的首次配置逻辑。

如果原版目录已经移走，可以不传 `-Source`，改为明确提供 `-CacheDirectory` 和 `-SharedDirectory`；此时必须已经有准备好的本地客户端。不要把 `-Source` 指向 `local-client`。

如果旧服务在 `terms/fetch`、`api/terms/fetch-agreements` 或 `version` 返回 4040，请更新服务端并重启。这些启动接口已经内置，不需要复制其他玩家的 fixtures。本地条款目录为空，不会伪造接受官方协议的记录。

## catalog 名称与请求路径

本地数字编号的 `.bin` 或 `catalogcached.bin` 是缓存来源名称，不是客户端请求路径。生成器保留 catalog 与配套 hash 的原始字节，在资源 manifest 中分别绑定到该客户端要求的固定路径；当前值见 [维护命令参数](../changelog.md#维护命令参数)。初始化脚本会完成映射，无需手动改文件名。

资源条目的 `cache_key`、Hash128、provider 和长度从 catalog 的结构字段读取，定位到缓存目录下的 `<cache_key>/<Hash128>/__info` 及其声明文件。Hash128 不当作文件 MD5 使用，文件内容另做 SHA-256 校验。

只生成索引的独立命令见[资源说明](assets.md)。更换客户端版本需要更新版本定义和结构验证，不能仅把文件改成旧名称。
