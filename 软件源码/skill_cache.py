"""Prepare an on-demand local copy so Codex can use scripts and relative references."""
import io
import os
import shutil
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath
from ai_reader import readonly
from skill_library import members, card

def paths(root,c):
    directory=root/"skill-cache"/c["package"]
    return directory,directory.joinpath(*PurePosixPath(c["member"]).parts)

def prepare(root,ident):
    with closing(readonly(root)) as db:
        c=card(db,ident)
        if not c["package"]:raise ValueError("请先导入这个技能的 ZIP 原包。")
        directory,entry=paths(root,c)
        if entry.is_file():return dict(directory=str(directory),skill_file=str(entry))
        raw=db.execute("SELECT raw FROM skill_packages WHERE digest=?",(c["package"],)).fetchone()[0]
    directory.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory.parent) as tmp:
        stage=Path(tmp)/"package";stage.mkdir(mode=0o700)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            for info in members(z):
                target=stage.joinpath(*PurePosixPath(info.filename).parts)
                target.parent.mkdir(parents=True,exist_ok=True)
                with target.open("xb") as out,z.open(info) as source:shutil.copyfileobj(source,out,1024*1024)
                if info.external_attr>>16 & 0o100:target.chmod(0o700)
        try: os.rename(stage,directory)
        except OSError:
            if not entry.is_file():raise
    return dict(directory=str(directory),skill_file=str(entry))

