# 随包工具:cmd_Decompiler 1.3.16

| 项 | 内容 |
|---|---|
| 来源 | bo3b/3Dmigoto 官方 GitHub release 里的独立包 `cmd_Decompiler-1.3.16.zip`(https://github.com/bo3b/3Dmigoto/releases) |
| 原 zip SHA-256 | 5E72E067DFCB15C36F106EFA74D805055EEC5314DC84B8FCA8E65D835683A1B2 |
| `cmd_Decompiler.exe` | 525,312 B,SHA-256 67582CED9261B8FB23A50CEE09C788C821D0524D40264721369B410D5321DAB8 |
| `d3dcompiler_46.dll` | 3,231,832 B,SHA-256 60F76EC7169397C425023D5927A3C3C34599FA329814053CACE6171E20ADB353(微软的 D3D 编译器运行库,官方 zip 里就带着) |
| 改动 | 无;两个文件由上面那个 zip 原样解出 |
| 源码 | https://github.com/bo3b/3Dmigoto/tree/1.3.16(标签 1.3.16 = 提交 `cbc4993ca67b6d639e06c578d4e3dc8b3780243f`) |

## 许可

- 3Dmigoto 源码是 **MIT** 许可(`LICENSE.MIT.txt`)。`COPYING.txt` 另外说明:3Dmigoto 注入用的 d3d11.dll 链接了 Nektra 的 Deviare-InProcess 库,
  那个库是 **GPLv3**(`LICENSE.GPL.txt`),以库的形式连同 Deviare 一起分发时,3Dmigoto 整体可能要按 GPLv3。
- `cmd_Decompiler.exe` 是独立的命令行反编译器,**不链接 Deviare**(2026-09-11 扫二进制:没有任何 Deviare / Nkt 字样,只导入 D3DCOMPILER_46、KERNEL32、USER32 等系统库)
  ⇒ 按 MIT 分发,随附版权与许可声明即可。
- 本目录原样放着上游 1.3.16 标签根目录的三份许可文件(下载后逐字节核对过 GitHub 记录的 git blob):

| 文件 | 大小 | git blob | SHA-256 |
|---|---|---|---|
| `COPYING.txt` | 1,156 B | 088c22a68161… | 025A6A5AD7397BD1D02E69702E65A886955E7360C7B86B9B3373B814BC219050 |
| `LICENSE.MIT.txt` | 1,147 B | 33429166310d… | 9DEC81F32ECA02DF93B8F64A80C234486B6D013B0F14A54B2D1874010A093C83 |
| `LICENSE.GPL.txt` | 35,147 B | 94a9ed024d38… | 8CEB4B9EE5ADEDDE47B31E975C1D90C73AD27B6B165A1DCD80C7C545EB65B903 |

- MIT 声明里「作者名单见 AUTHORS.txt」指上游的 https://github.com/bo3b/3Dmigoto/blob/1.3.16/AUTHORS.txt 。
- `d3dcompiler_46.dll` 是微软 Windows SDK 的可再发行 D3D 编译器运行库,不归 3Dmigoto 的许可管;3Dmigoto 官方包本来就随带它。

## 用法

- `cmd_Decompiler.exe -D <bin>`:在 bin 旁边出 `.hlsl`
- `cmd_Decompiler.exe --disassemble-ms <bin>`:出 `.msasm`
