# 勋的软件

这是可在 Mac 和 Windows 11 恢复的私人资料库。换机发布包含程序和全部在库资料。源代码在「软件源码」，导入清单和使用示意图在「资料整理记录」。

## 换机时交给 Codex

> 在当前电脑上恢复 GitHub 私有仓库 ft807275/xun-software 的「勋的软件」。按 README 下载最新完整换机发布，校验全部分卷和资料更新包，恢复到新的安装目录并首次启动。核对行业库、产品图库、DEWEWE 与 HiveCush 的建站项目、提示词与原文，并保留此电脑已有的数据。

## 下载与打开

1. 登录拥有该私有仓库访问权限的 GitHub 账号，打开 [换机发布](https://github.com/ft807275/xun-software/releases)。克隆仓库，检出对应发布标签，把全部换机分卷、最新程序包「xun-program-2.9.71-clipboard.zip」和最新资料包「xun-records-2.9.71-bilingual.zip」下载到同一个文件夹。建议用有至少 90 GB 剩余空间的硬盘。
2. 从仓库根目录运行 `python3 scripts/prepare.py downloads 新安装目录`，Windows 可用 `py -3 scripts/prepare.py downloads 新安装目录`。Windows 没有 Python 时，下载并解压同次发布的程序包，用其中的「勋的软件/runtime/win/python.exe」运行该命令。脚本会校验、合并分卷，恢复资料并补齐之后归档的建站记录，最后生成一个新的安装文件夹。
3. 从生成的安装文件夹打开「Mac-打开词库.command」或「Windows-打开词库.cmd」。新 Mac 第一次运行可能需要安装 Python，程序包自带安装器。
4. 进入系统首页核对数据，再进「软件与建站资料 → 项目提示词」，打开 DEWEWE 或 HiveCush，查看当前阶段、各步骤提示词和原文。

有 GitHub CLI 时可一次下载。下面的 `downloads` 是下载目录，`xun-restored` 是新的安装目录。

```sh
gh release download v2.9.71 --repo ft807275/xun-software --pattern 'xun-restore-*.part*' --pattern 'xun-records-2.9.71-bilingual.zip' --pattern 'xun-program-2.9.71-clipboard.zip' --dir downloads
python3 scripts/prepare.py downloads xun-restored
```

「release-manifest.json」记录本版的资料统计、分卷顺序和校验值。脚本会保留下载的完整换机 ZIP 和新安装目录。

## 建站工作目录

如需在新电脑接着使用已有站点源码、交接文件和研究输出，下载同一次发布的 `xun-project-files-2.9.71.zip`。解压后将建站项目关联到新机对应目录，进项目的 Codex 归档设置重新绑定本机文件夹。已导入的历史和资料随完整换机包恢复。继续开发时，将相应的工作目录用 Codex 打开。私人登录、远程访问密码、仓库凭据和网站密钥由新机单独配置。

## 让新电脑上的 Codex 读取资料

打开恢复后的软件，进入「软件与建站资料 → Skills 技能包」，使用「连接 Codex」登记新机的本地资料路径。也可从「行业关键词库 → AI 取词」复制这台电脑的连接配置。首次连接后，从新电脑的 Codex 查看 DEWEWE 第 6 步提示词，核对链接与原文。要继续自动归档新对话，就在对应项目上登记新机的工作目录。换机发布保留已归档的对话和原文。

大磊课程在「软件与建站资料 → 建站知识库 → 大磊建站流程」。课程六步、每步提示词与技能原包都随资料恢复。
