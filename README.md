# 勋的软件

这是可在 Mac 和 Windows 11 恢复的私人资料库。换机发布包含程序和全部在库资料。源代码在「软件源码」，导入清单和使用示意图在「资料整理记录」。

## 换机时交给 Codex

> 在当前电脑上恢复 GitHub 私有仓库 ft807275/xun-software 的「勋的软件」。按 README 下载最新完整换机发布，逐个校验分卷，完整解压并首次启动。核对行业库、产品图库、DEWEWE 与 HiveCush 的建站项目、提示词与原文，并保留此电脑已有的数据。

## 下载与打开

1. 登录拥有该私有仓库访问权限的 GitHub 账号，打开 [换机发布](https://github.com/ft807275/xun-software/releases)。克隆源代码，下载同一发布中的所有 `xun-restore-*.part*` 到同一个文件夹。建议用有至少 90 GB 剩余空间的内置硬盘。
2. 检出对应版本。从仓库根目录运行 `python3 scripts/reassemble.py 下载文件夹`，Windows 使用 `py -3 scripts/reassemble.py 下载文件夹`。Windows 没有 Python 时，可先下载并解压同次发布的程序包，通过其中的 `勋的软件/runtime/win/python.exe` 运行这个脚本。脚本校验每个分卷和最终 ZIP 的 SHA-256。
3. 将生成的「勋的软件-Win11-Mac.zip」完整解压到新文件夹。Windows 双击「Windows-打开词库.cmd」，Mac 双击「Mac-打开词库.command」。首次启动会恢复并校验资料。出现选择旧资料目录的界面时，先核对本次解压目录是否包含 `library-data.zip`。
4. 进入系统首页核对数据，再进「软件与建站资料 → 项目提示词」，打开 DEWEWE 或 HiveCush，查看当前阶段、各步骤提示词和原文。

用 GitHub CLI 可以从仓库目录一次下载全部分卷。

```sh
gh release download v2.9.71 --repo ft807275/xun-software --pattern 'xun-restore-*.part*' --dir downloads
python3 scripts/reassemble.py downloads
```

「release-manifest.json」中包含本版资料统计、ZIP 校验值和分卷顺序。校验完整 ZIP 后，可保留它并移走已重组的下载分卷。

## 建站工作目录

如需在新电脑接着使用已有站点源码、交接文件和研究输出，下载同一次发布的 `xun-project-files-2.9.71.zip`。解压后将建站项目关联到新机对应目录，进项目的 Codex 归档设置重新绑定本机文件夹。已导入的历史和资料随完整换机包恢复。继续开发时，将相应的工作目录用 Codex 打开。私人登录、远程访问密码、仓库凭据和网站密钥由新机单独配置。
