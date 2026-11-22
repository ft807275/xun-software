"""Restore all industries atomically to a new directory."""

import argparse
import sqlite3
from transfer import inspect_backup
from workspaces import restore


def restore_with_feedback(archive, destination):
    print("正在读取备份，检查可用磁盘空间…", flush=True)
    details = inspect_backup(archive)
    if details["type"] != "backup":
        raise ValueError("请选择整库备份。若要从换机包恢复，请先解压并打开里面的启动文件。")
    print(f"将恢复 {details['databases']} 个资料库，预计占用 {details['restore_bytes'] / 10**6:,.1f} MB。", flush=True)

    def progress(stage, done, total):
        if stage == "extract":
            percent = done * 100 // max(1, total)
            if total >= 10**9:
                size = f"{done / 10**9:.2f} / {total / 10**9:.2f} GB"
            else:
                size = f"{done / 10**6:.2f} / {total / 10**6:.2f} MB"
            print(f"正在恢复文件 · {percent}% · {size}", flush=True)
        else:
            print(f"校验资料库 · {done} / {total}", flush=True)

    try:
        restore(archive, destination, progress)
    except sqlite3.Error as exc:
        raise ValueError("备份中的数据库无法读取，请检查备份文件。") from exc
    print("资料恢复完成。", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("archive")
    p.add_argument("destination")
    args = p.parse_args()
    try:
        restore_with_feedback(args.archive, args.destination)
    except (ValueError, OSError) as error:
        p.exit(1, str(error) + "\n")
