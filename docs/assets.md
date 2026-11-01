# 本地游戏资源接入

[文档目录](README.md) · [主数据](masterdata.md)

PC 首次部署直接运行 [PC 首次启动](first-start.md) 中的 `setup-pc.ps1` 即可自动完成索引生成与 catalog 路径映射。以下独立命令供日常检查缓存或手动维护环境使用。

## 1. 生成 PC 资源索引

先在仓库根目录 PowerShell 中加载 [维护命令参数](../changelog.md#维护命令参数) 变量块，再运行：

```powershell
.\.venv\Scripts\python.exe -m dotabyss_ps.asset_index --catalog '<实际 catalog 文件>' --catalog-hash '<实际 hash 文件>' --output '.\artifacts\resource-url-index.json'
```

生成器解析 Addressables v2 二进制 catalog，提取每条资源 URL 对应的 `cache_key`、Hash128、provider 与声明长度。

## 2. 暂存与激活资源

导入前需确保已激活对应客户端版本的主数据。在同一 PowerShell 窗口中执行：

```powershell
.\.venv\Scripts\python.exe -m dotabyss_ps.assets --data-dir $dataDirectory stage --index .\artifacts\resource-url-index.json --catalog '<catalog文件>' --catalog-hash '<hash文件>' --cache-root '<游戏目录>/ドットアビスX_Data/Caches' --catalog-relative-path $catalogRelativePath --catalog-hash-relative-path $catalogHashRelativePath --source 'PC 本地缓存'
.\.venv\Scripts\python.exe -m dotabyss_ps.assets --data-dir $dataDirectory activate '<stage 返回的 assets 版本>'
.\.venv\Scripts\python.exe -m dotabyss_ps.assets --data-dir $dataDirectory status
```

- 若本地缓存存在缺失文件，可添加 `--allow-partial` 暂存并记录缺失清单。
- 服务端按文件内容的 SHA-256 将资源存为 `assets/blobs/<sha256>`，清单保存在 `assets/manifests/<assets版本>.json`，当前激活版本记录于 `assets/active.json`。

## 3. 缓存结构与格式校验

导入器按 `<缓存根目录>/<cache_key>/<Hash128>/__info` 定位缓存文件，并执行完整性校验：

- **UnityFS 资源包（`__data`）**：校验文件头签名、版本、声明长度与 block-info 范围。
- **CRI AFS2 音频**：校验头部、表长度、对齐偏移与文件总长度（参考 [vgmstream awb 解析](https://github.com/vgmstream/vgmstream/blob/master/src/meta/awb.c)）。
- **CRI USM 视频**：逐块校验声明长度、载荷偏移、padding 与流块签名（参考 [WannaCRI usm 解析](https://github.com/donmai-me/WannaCRI/blob/master/wannacri/usm/chunk.py)）。

## 4. HTTP 资源服务

`GET /resources/...` 根据当前激活的 manifest 返回对应 blob 及 SHA-256 ETag（支持 `304 Not Modified` 条件请求）。带 Hash128 后缀的资源启用长期缓存，catalog 与 hash 路径使用 `no-cache` 策略以便版本切换后即时生效。
