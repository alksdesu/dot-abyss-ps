# Android 本地协议适配器

面向 Android ARM64 Unity IL2CPP 客户端（LemonLoader / MelonLoader 环境）的本地协议重定向与诊断插件。

## 核心功能

- **配置开关**：通过 `UserData/DotAbyssLocal/config.json` 控制，默认关闭，修改后重启生效。
- **路由重定向**：Hook `RuntimeConfig.GetApiUrl()`、`ApiManager.RefreshConfig(string)` 及 `UnityWebRequest`，将游戏 API 请求指向本地服务端并注入本地 `x-olg-session` 与 `api-token`。
- **明文协议适配**：Hook `ApiCrypt` 的 `EncryptBody`、`DecryptBody`、`EncryptLaravel`、`DecryptLaravel`，与本地服务端直接交互明文 JSON。
- **本地会话与平台替换**：接管 `DmmSdk.Initialize` 与 `DmmSdkUnityIap.Initialize`，通过 `POST /local/login` 建立本地会话，替换原生 `LoginDmmAndroidAsync` 登录流。
- **版本校验跳过**：支持配置 `IgnoreVersionChecks`（开启 `ApiManager.SkipCheckVersion`）。
- **纯观察模式（`ObserveOnly=true`）**：保留原版联网与平台登录，仅通过 Hook 记录请求路由结构与状态机阶段，可选开启 `CaptureRedactedResponses=true` 将脱敏响应保存至 `UserData/DotAbyssLocal/responses`。
- **MuMu 远跳板支持（`AllowFarTrampolines=true`）**：针对模拟器中 Dobby 近跳板空间不足（`trampoline.near_unavailable`）的情况，在挂载 Hook 前调用 `libmain.so` 的 `dobby_set_near_trampoline(1)` 允许回退至远跳板。

## 编译

准备好 .NET SDK 与 APK 解包目录（默认读取 `..\..\dotabyss_unpacked`，可通过 `-GameRoot` 指定），在 PowerShell 中执行：

```powershell
pwsh -File .\android\build.ps1
```

编译产物输出至 `android/dist/DotAbyss.Local.dll`。

## 安装与联调

1. 启动本地 Python 服务端（监听 `127.0.0.1:18081`）。
2. 连接设备 ADB，执行端口转发：`adb reverse tcp:18081 tcp:18081`。
3. 将 `android/dist/DotAbyss.Local.dll` 放入设备 MelonLoader 的 `Mods` 目录。
4. 首次启动游戏生成默认配置文件，将 `UserData/DotAbyssLocal/config.json` 中的 `Enabled` 设为 `true` 后重启游戏。

## 契约测试

运行本地单元测试与契约检查：

```powershell
dotnet run --project .\android\tests\AdapterChecks.csproj -c Release
```

联调已启动的本地服务端：

```powershell
dotnet run --project .\android\tests\AdapterChecks.csproj -c Release -- --server http://127.0.0.1:18081
```
