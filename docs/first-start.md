# PC 首次启动

[文档目录](README.md) · [启动器与控制台](../console/README.md)

按 [适配记录](../changelog.md) 准备好对应版本的 PC 客户端、已下载资源、Python 和 .NET SDK。以下命令在仓库根目录执行（将 `D:\dot\dotabyss_x_cl` 替换为自己的原版游戏目录）。

## 1. 初始化客户端与资源

```powershell
.\setup-pc.ps1 -Source 'D:\dot\dotabyss_x_cl'
```

脚本会自动创建 Python 虚拟环境、安装依赖，并执行以下步骤：

- 校验游戏版本，将客户端准备到仓库相邻的 `dotabyss_pc/local-client`（保留原版目录不动）。
- 生成本机 release 配置，自动关联缓存来源与隔离数据目录。
- 按内容 SHA-256 匹配对应版本的 catalog、hash 与主数据。
- 解码 catalog 生成资源索引，校验并导入主数据与资源后自动激活。
- 若客户端内已安装好加载器并生成了 interop，则自动编译并安装私服插件。

插件配置文件 `pc-local.json` 会在启动器首次启动游戏时自动生成。资源索引与缺失清单保存在数据目录的 `setup/` 下（默认目录见 [维护命令参数](../changelog.md#维护命令参数)）。

### 指定缓存目录

脚本默认按以下顺序查找资源缓存：游戏目录旁的 `resource-cache` ➔ 当前 Windows 用户的原版游戏缓存（`%USERPROFILE%\AppData\LocalLow\EXNOA LLC_\ドットアビスX`）➔ 已有的隔离缓存。

目录结构示例：

```text
D:\dot\
  dotabyss_x_cl\
    ドットアビスX.exe
    ドットアビスX_Data\Caches\...
  resource-cache\
    com.unity.addressables\...
    DownloadCache\...
```

若缓存存放在其他位置，可通过参数显式指定：

```powershell
.\setup-pc.ps1 -Source 'D:\dot\dotabyss_x_cl' -CacheDirectory 'D:\cache\resource-cache' -SharedDirectory 'D:\cache\Shared'
```

- `-CacheDirectory`：包含 `com.unity.addressables` 与 `DownloadCache` 的目录。
- `-SharedDirectory`：包含资源缓存桶的目录（如 `Shared` 或 `ドットアビスX_Data\Caches`）。
- `-Check`：仅检查来源与索引，不写入文件。
- `-AllowPartial`：当本地缓存存在部分资源缺失时，仍强制激活已导入的资源集合。

## 2. 首次准备加载器

若第 1 步返回 `ready: false` 并提示缺少 interop，请按以下步骤在生成的 `dotabyss_pc/local-client` 中配置加载器：

1. 下载并解压对应版本的 BepInEx IL2CPP Windows x64（版本与下载链接见 [运行与构建环境](../changelog.md#运行与构建环境)），使加载器文件与 `ドットアビスX.exe` 同级。
2. 按 [兼容构建说明](../third_party/Il2CppInterop/COMPATIBILITY.md) 将仓库根目录的两个修补版 `Il2CppInterop.*.dll` 覆盖到 `BepInEx/core/`。
3. 启动一次 `dotabyss_pc/local-client/ドットアビスX.exe`，等待 BepInEx 自动生成 `BepInEx/interop/Project.dll`（日志位于 `BepInEx/LogOutput.log`），随后关闭游戏。

## 3. 编译插件并打开控制台

```powershell
.\setup-pc.ps1 -PluginOnly
.\start-console.ps1 -Port 18083
```

插件会直接引用本地客户端的 core 与 interop 编译并安装到 `BepInEx/plugins/`。

打开启动器后，点击“启动服务”，新建或选择存档，再点击“启动游戏”即可进入私服。繁体翻译可在启动器“繁体中文”栏一键安装（详见 [翻译说明](../pc-translation/README.md)）。

## 补充说明

- **切换 Windows 启动环境**：启动器会将已绑定缓存复制到当前环境并记录绑定，原目录保留；目标已有未绑定数据时会提示处理。绑定备份位于客户端的 `profile-context-backups/`。
- **重新执行初始化**：退出游戏后直接重跑第 1 步命令即可，已有配置与已校验资源会自动复用。
- **原版目录已移除**：若已准备好 `local-client` 且移除了原版目录，可省略 `-Source`，直接传入 `-CacheDirectory` 与 `-SharedDirectory`。
- **Catalog 路径映射**：本地缓存中的数字文件名（如 `1791059991.bin` 或 `catalogcached.bin`）会被自动映射到客户端固定的请求路径，无需手动重命名。独立生成索引的命令见 [资源说明](assets.md)。
