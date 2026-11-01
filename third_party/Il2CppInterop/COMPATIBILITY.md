# Il2CppInterop 兼容构建

基于上游 [BepInEx/Il2CppInterop](https://github.com/BepInEx/Il2CppInterop)（基线提交 `dbda1cb353b0f4253345dc45136d170b9e50a5a0`）构建，修复了 Windows x64 IL2CPP 环境下的参数传递与装箱问题。文件哈希清单见 [兼容库指纹](../../changelog.md#兼容库指纹)。

## 修改内容

- `Il2CppInterop.HarmonySupport/Il2CppDetourMethodPatcher.cs` & `ValueTypeArgument.cs`：遵循 Windows x64 ABI 处理小型值类型的按值传参，保留实例与引用参数传递方式。
- `Il2CppInterop.Runtime/IL2CPP.cs`：避免已解包的泛型值类型被重复装箱。

## 校验与替换

在游戏目录中运行以下命令可查看当前 DLL 哈希：

```powershell
Get-FileHash .\BepInEx\core\Il2CppInterop.Runtime.dll, .\BepInEx\core\Il2CppInterop.HarmonySupport.dll -Algorithm SHA256
```

退出游戏，备份 `BepInEx/core/` 下的两个同名文件，再将仓库根目录提供的两个修补版 DLL 覆盖到 `BepInEx/core/` 即可。

## 源码构建

按本目录 `global.json` 安装对应 .NET SDK（8.0），运行：

```powershell
dotnet build Il2CppInterop.HarmonySupport/Il2CppInterop.HarmonySupport.csproj -c Release
```

构建产物分别位于 `bin/Il2CppInterop.Runtime/net6.0/` 和 `bin/Il2CppInterop.HarmonySupport/net6.0/`。

## 许可

遵循上游 LGPL-3.0-only 许可，详见 [LICENSE](LICENSE) 与 [COPYING.GPL-3.0](COPYING.GPL-3.0)。
