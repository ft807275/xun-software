"""Inspect and update the private local keyword-library connection."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import NamedTemporaryFile
from threading import Lock

import ai_reader

try:
    import tomllib
except ImportError:
    try:
        from pip._vendor import tomli as tomllib
    except ImportError:
        tomllib = None


NAME = "industry-keywords"
LOCK = Lock()
TABLE = re.compile(r"(?m)^[ \t]*\[\[?[^\r\n]+?\]\]?[ \t]*(?:#[^\r\n]*)?\r?$")
MANAGED = re.compile(r"""\[\s*mcp_servers\s*\.\s*(?:industry-keywords|"industry-keywords"|'industry-keywords')\s*\]""")
STRING = r"""(?:"(?:[^"\\\r\n]|\\.)*"|'[^'\r\n]*')"""
VALUES = {
    "command": rf"(?:{STRING})",
    "args": rf"\[(?:{STRING}|#[^\r\n]*|[\s,])*\]",
    "enabled": r"(?:true|false)",
}


def config_path():
    return (Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml").resolve()


def parse(text):
    if tomllib is None:
        raise ValueError("本机运行环境暂时无法读取 Codex 配置。")
    return tomllib.loads(text)


def descriptor(settings):
    return settings.get("mcp_servers", {}).get(NAME)


def managed(config):
    if not isinstance(config, dict) or not isinstance(config.get("command"), str):
        return None
    args = config.get("args")
    if not isinstance(args, list) or len(args) != 6 or not all(isinstance(a, str) for a in args):
        return None
    if args[:3] != ["-X", "utf8", "-B"] or args[4] != "--data" or "\0" in "".join([config["command"], *args]):
        return None
    program, root = Path(args[3]), Path(args[5])
    if program.name != "ai_reader.py" or not program.is_absolute() or not root.is_absolute() or "url" in config:
        return None
    return program, root


def check_reader(command, args):
    initialize = {"protocolVersion": "2025-03-26", "clientInfo": {"name": "勋的软件", "version": ai_reader.APP_VERSION},
                  "capabilities": {}}
    queries = [
        ("initialize", initialize),
        ("tools/call", {"name": "list_industries", "arguments": {}}),
        ("tools/call", {"name": "search_keywords", "arguments": {"industry": 1, "limit": 1}}),
    ]
    encoded = "\n".join(json.dumps(dict(jsonrpc="2.0", id=i, method=method, params=params))
                         for i, (method, params) in enumerate(queries, 1)) + "\n"
    try:
        run = subprocess.run(
            [command, *args], input=encoded.encode("utf-8"), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, check=True, timeout=8,
        )
        replies = {item["id"]: item["result"] for item in map(json.loads, run.stdout.splitlines())}
        server = replies[1]["serverInfo"]
        if server["name"] != NAME or replies[2].get("isError") or replies[3].get("isError"):
            return None
        industries = json.loads(replies[2]["content"][0]["text"])["industries"]
        return {"version": server["version"], "industryCount": len(industries)}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, IndexError):
        return None


def status(root):
    current = ai_reader.config(root)
    result = dict(config=current, current=str(root.resolve()))
    try:
        path = config_path()
        if not path.is_file():
            return dict(result, state="missing")
        config = descriptor(parse(path.read_bytes().decode("utf-8")))
    except (OSError, ValueError, AttributeError, RuntimeError):
        return dict(result, state="invalid")
    if config is None:
        return dict(result, state="missing")
    target = managed(config)
    if not target:
        return dict(result, state="custom")
    program, saved = target
    result["configured"] = config["args"][-1]
    try:
        if any(config.get(key) for key in ("env", "env_vars", "cwd")) or type(config.get("enabled", True)) is not bool:
            return dict(result, state="custom")
        if saved.resolve() != root.resolve():
            return dict(result, state="different")
        if config.get("enabled") is False:
            return dict(result, state="disabled")
        wanted = current["mcpServers"][NAME]
        support = Path.home() / "Library/Application Support/ZhijianKeywordSoftware"
        allowed = (
            Path(wanted["args"][3]), support / "program/ai_reader.py",
            Path.home() / "Applications/勋的软件.app/Contents/Resources/ai_reader.py",
        )
        if (Path(config["command"]) != Path(wanted["command"]) and config["command"] != "/usr/bin/python3"
            or not any(program.resolve() == p.resolve() for p in allowed)
            or not program.is_file() or not Path(config["command"]).is_file()):
            return dict(result, state="stale")
        proof = check_reader(config["command"], config["args"])
    except (OSError, ValueError, RuntimeError):
        return dict(result, state="stale")
    if proof is None:
        return dict(result, state="failed")
    required = {"list_industries", "search_keywords"}
    enabled = config.get("enabled_tools")
    disabled = config.get("disabled_tools", [])
    limited = (isinstance(enabled, list) and not all(name in enabled for name in required)
               or isinstance(disabled, list) and any(name in disabled for name in required))
    state = "stale" if proof["version"] != ai_reader.APP_VERSION else "limited" if limited else "ready"
    return dict(result, state=state, **proof)


def rewrite(text, settings, old, wanted):
    newline = "\r\n" if "\r\n" in text else "\n"
    encode = lambda value: json.dumps(value, ensure_ascii=False)
    changes = {key: wanted[key] for key in ("command", "args") if not old or old.get(key) != wanted[key]}
    if old and old.get("enabled") is False:
        changes["enabled"] = True
    if not changes:
        return text
    if old is None:
        updated = text + newline + f"[mcp_servers.{NAME}]" + newline + "".join(
            f"{key} = {encode(value)}{newline}" for key, value in changes.items()
        )
    else:
        headers = list(TABLE.finditer(text))
        matches = [i for i, h in enumerate(headers) if MANAGED.match(h[0].lstrip())]
        if len(matches) != 1:
            raise ValueError("这份连接使用自定义格式。可以复制下方配置，在 Codex 设置中核对。")
        index = matches[0]
        start = headers[index].end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        section = text[start:end]
        for key, value in changes.items():
            field = rf"(?m)^([ \t]*{key}[ \t]*=[ \t]*){VALUES[key]}(?=[ \t]*(?:#|\r?$))"
            section, changed = re.subn(field, lambda m: m[1] + encode(value), section)
            if changed != 1:
                raise ValueError("这份连接使用自定义格式。可以复制下方配置，在 Codex 设置中核对。")
        updated = text[:start] + section + text[end:]
    expected = deepcopy(settings)
    expected.setdefault("mcp_servers", {}).setdefault(NAME, {}).update(changes)
    if parse(updated) != expected:
        raise ValueError("配置格式需要核对。其他 Codex 设置已保留。")
    return updated


def connect(root, switch_from=None):
    wanted = ai_reader.config(root)["mcpServers"][NAME]
    with LOCK:
        path = config_path()
        try:
            original = path.read_bytes() if path.exists() else b""
            text = original.decode("utf-8")
            settings = parse(text)
            old = descriptor(settings)
        except (OSError, ValueError, AttributeError) as exc:
            raise ValueError("请先检查 Codex 的本机配置。") from exc
        if old is not None:
            target = managed(old)
            if (not target or any(old.get(key) for key in ("env", "env_vars", "cwd"))
                or type(old.get("enabled", True)) is not bool):
                raise ValueError("此名称已有自定义连接。可以在 Codex 设置中核对。")
            if target[1].resolve() != root.resolve() and old["args"][-1] != switch_from:
                raise ValueError("当前连接有所不同，请重新检查并确认要切换的资料库。")
        updated = rewrite(text, settings, old, wanted)
        if updated != text:
            if not check_reader(wanted["command"], wanted["args"]):
                raise ValueError("当前资料库还没有通过读取测试，请重新打开软件后再试。")
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
                draft = Path(tmp.name)
                tmp.write(updated.encode("utf-8"))
                tmp.flush()
                os.fsync(tmp.fileno())
            try:
                if (path.read_bytes() if path.exists() else b"") != original:
                    raise ValueError("Codex 配置刚刚有改动，请重新检查连接。")
                if path.exists():
                    draft.chmod(path.stat().st_mode & 0o777)
                draft.replace(path)
            finally:
                draft.unlink(missing_ok=True)
    result = status(root)
    result["message"] = "已通过本机读取测试" if result["state"] == "ready" else "已写入连接配置"
    return result
