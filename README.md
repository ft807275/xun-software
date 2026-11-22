# 勋的软件

这是可在 Mac 和 Windows 11 恢复的私人资料库。换机发布包含程序和全部在库资料。源代码在「软件源码」，导入清单和使用示意图在「资料整理记录」。

## 换机时交给 Codex

> 在当前电脑上恢复 GitHub 私有仓库 ft807275/xun-software 的「勋的软件」。按 README 下载并恢复最新换机备份。用新的安装目录，核对关键词、产品图原件、建站项目和提示词原文。

## 下载与打开

当前资料快照为 **2026-11-22 17:45（北京时间）**。[打开本次发布](https://github.com/ft807275/xun-software/releases/tag/backup-2026-11-22-1745)

登录拥有该私有仓库访问权限的 GitHub 账号。首次换机需下载本次发布和 [基础换机发布 v2.9.71](https://github.com/ft807275/xun-software/releases/tag/v2.9.71) 中 `release-manifest.json` 指定的附件。两者一起恢复当前数据。基础发布使用分卷和建站工作目录 ZIP，本次发布提供最新程序、资料和工作目录的更新。已有基础分卷可经校验后直接复用。建议选至少有 90 GB 剩余空间的硬盘，Windows 可使用简短目录如 `C:\Xun`。

在克隆的仓库根目录运行下列命令。有 GitHub CLI 时先用 `gh auth login` 登录。

```sh
git checkout backup-2026-11-22-1745
python3 scripts/download.py downloads
python3 scripts/prepare.py downloads xun-restored
```

Windows 可将 `python3` 换成 `py -3`。也可以从两份发布手动下载清单指定的分卷、程序包、资料更新包、建站工作目录及其更新包，把它们放进同一个 `downloads` 文件夹，然后运行恢复命令。Windows 如需随包的 Python，可以解压本次程序包并用里面的「勋的软件/runtime/win/python.exe」运行恢复命令。

进入生成的文件夹，打开「Mac-打开词库.command」或「Windows-打开词库.cmd」。这次备份包含关键词库、产品原图、建站进度、提示词及已归档原文。更新后的侧栏和项目改名功能随程序包恢复。

## 建站工作目录

恢复命令会同时解出「建站工作目录」，包括两处站点源码、交接文件和研究输出的基础文件与本次更新。继续开发时用 Codex 打开新电脑上的相应工作目录，并在软件中重新关联该目录，继续自动归档新对话。站点登录、远程访问密码、仓库凭据和网站密钥由新机单独配置。

## 让新电脑上的 Codex 读取资料

打开恢复后的软件，进入「软件与建站资料 → Skills 技能包」，使用「连接 Codex」登记新机的本地资料路径。也可从「行业关键词库 → AI 取词」复制这台电脑的连接配置。首次连接后，从新电脑的 Codex 查看 DEWEWE 第 6 步提示词，核对链接与原文。要继续自动归档新对话，就在对应项目上登记新机的工作目录。换机发布保留已归档的对话和原文。

大磊课程在「软件与建站资料 → 建站知识库 → 大磊建站流程」。课程六步、每步提示词与技能原包都随资料恢复。

课程视频整理出的「拓词与竞品取词」源文件在 [skills/b2b-seo-keyword-sourcing](skills/b2b-seo-keyword-sourcing)。资料恢复后也能在「Skills 技能包」下载同一版本，供 Codex 使用。
