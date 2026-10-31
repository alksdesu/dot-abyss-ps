# Il2CppInterop 兼容构建

上游：[BepInEx/Il2CppInterop](https://github.com/BepInEx/Il2CppInterop)。基线提交与分发文件哈希见[兼容库指纹](../../changelog.md#兼容库指纹)。

本目录保留构建根目录两个 DLL 所需的 Common、Runtime、HarmonySupport 项目及上游构建引用。修改后的源代码已包含补丁，不需要再次应用 `local-changes.patch`。

## 适用环境

已验证的客户端、加载器和运行时组合见[运行与构建环境](../../changelog.md#运行与构建环境)。版本号相同不代表 DLL 相同，应同时核对 SHA256。

## 文件核对

在游戏目录中运行：

```powershell
Get-FileHash .\BepInEx\core\Il2CppInterop.Runtime.dll, .\BepInEx\core\Il2CppInterop.HarmonySupport.dll -Algorithm SHA256
```

每个文件应分别匹配[兼容库指纹](../../changelog.md#兼容库指纹)中的原版或修补版哈希。两个文件都已是修补版时无需重复替换；未知哈希先核对来源和运行环境。退出游戏后备份两个文件，再按根目录 README 成对替换；回滚也应恢复两个文件。

## 本地修改

- `Il2CppInterop.HarmonySupport/Il2CppDetourMethodPatcher.cs` 和新增 `ValueTypeArgument.cs`：按 Windows x64 ABI 处理小型值类型的按值参数，保留实例和引用参数的传递方式。
- `Il2CppInterop.Runtime/IL2CPP.cs`：避免已经解包的泛型值类型再次装箱。

根目录分发的两个 DLL 与本地已验证的构建产物哈希一致。

## 构建

按本目录 `global.json` 选择并安装 .NET SDK，在本目录运行：

```powershell
dotnet build Il2CppInterop.HarmonySupport/Il2CppInterop.HarmonySupport.csproj -c Release
```

首次构建需要恢复项目声明的 NuGet 依赖。输出分别位于 `bin/Il2CppInterop.Runtime/` 和 `bin/Il2CppInterop.HarmonySupport/` 下的目标框架目录，完整路径以构建输出为准。构建路径或 SDK 不同可能导致产物哈希不同。

`Il2CppInterop.Runtime/Libs/Il2Cppmscorlib.dll` 是上游仓库自带的构建引用，不需要复制到游戏中。

## 许可

Il2CppInterop 使用 LGPL-3.0-only，见 [LICENSE](LICENSE)；其引用的 GPLv3 全文见 [COPYING.GPL-3.0](COPYING.GPL-3.0)。原有作者和版权说明均保留。
