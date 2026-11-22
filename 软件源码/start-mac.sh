#!/bin/zsh
set -eu
base="$(cd "$(dirname "$0")/.." && pwd)"
entry="$base/program/portable.py"

usable_python() {
  [[ -x "$1" ]] && "$1" -I -B -c 'import sqlite3, sys; assert sys.version_info >= (3, 9); sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE check_fts USING fts5(text)")' >/dev/null 2>&1
}

if /usr/bin/xcode-select -p >/dev/null 2>&1 &&
    usable_python /usr/bin/python3; then
  exec /usr/bin/python3 -X utf8 -B -u "$entry" "$@"
fi

# Finder may not inherit the user's shell PATH.
for python in /Library/Frameworks/Python.framework/Versions/[0-9]*/bin/python3(NOn) \
    /opt/homebrew/bin/python3 /usr/local/bin/python3 /opt/local/bin/python3; do
  if usable_python "$python"; then
    exec "$python" -X utf8 -B -u "$entry" "$@"
  fi
done

installer="$base/runtime/python-3.14.10-macos11.pkg"
digest=286c7018aa2730f6747ca433dccdc2b31be45f078a9ea0ffa44d5f06368fd2d7
if [[ -r "$installer" ]] &&
    actual="$(/usr/bin/shasum -a 256 < "$installer")" &&
    [[ "${actual%% *}" == "$digest" ]]; then
  printf '%s\n' "首次使用需要安装免费的 Python 运行环境。"
  if ! /usr/bin/open -a Installer "$installer"; then
    printf '%s\n' "请打开软件包中的 runtime 文件夹，双击 python-3.14.10-macos11.pkg。"
  fi
else
  printf '%s\n' "找不到完整的 Python 安装包。请重新解压换机包，或从以下地址获取 Python 官方 macOS 安装器。" \
    "https://www.python.org/downloads/macos/"
fi
printf '%s\n' "安装完成后，请再次打开刚才的勋的软件启动文件。"
exit 1
