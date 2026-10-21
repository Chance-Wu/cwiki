"""修复被本机透明加密软件(DLP)破坏的 venv entry_points.txt。

背景：DLP 按扩展名加密 .txt，site-packages 的 */entry_points.txt 被覆盖为
密文（含 ``|orl_`` 标记），导致 importlib.metadata 解析失败、pytest 启动即崩。

恢复策略（内容均须通过 dist-info/RECORD 中安装时记录的 sha256 验证才写回）：
1. 同版本包的系统 Python site-packages
2. pip http-v2 下载缓存中的 wheel（gzip 解压后 zip）
3. 均无来源时报告，可联网后 ``pip install --force-reinstall --no-deps <pkg>``

用法：python scripts/fix_dlp_entry_points.py
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import pathlib
import sys
import zipfile

VENV_SP = pathlib.Path(r"D:\cwiki\.venv\Lib\site-packages")
SYS_SP = pathlib.Path(
    r"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\Lib\site-packages"
)
PIP_CACHE = pathlib.Path(r"C:\Users\Administrator\AppData\Local\pip\cache\http-v2")


def b64sha256(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def record_sha256(dist_info: pathlib.Path) -> str | None:
    """RECORD 中 entry_points.txt 安装时的 sha256（urlsafe b64，无填充）。"""
    rec = dist_info / "RECORD"
    if not rec.exists():
        return None
    try:
        text = rec.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    for line in text.splitlines():
        if line.startswith(f"{dist_info.name}/entry_points.txt,"):
            part = line.split(",")[1]
            if part.startswith("sha256="):
                return part[len("sha256=") :]
    return None


def is_encrypted(ep: pathlib.Path) -> bool:
    try:
        ep.read_bytes().decode("utf-8")
    except (UnicodeDecodeError, OSError):
        return True
    return False


def try_system_python(dn: str, want: str) -> bytes | None:
    for src in sorted(SYS_SP.glob(f"{dn.split('-')[0]}-*.dist-info/entry_points.txt")):
        try:
            data = src.read_bytes()
            data.decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if b64sha256(data) == want:
            return data
    return None


def try_pip_cache(want_by_dn: dict[str, str]) -> dict[str, bytes]:
    got: dict[str, bytes] = {}
    if not PIP_CACHE.exists():
        return got
    for f in PIP_CACHE.rglob("*.body"):
        if len(got) == len(want_by_dn):
            break
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        if len(raw) < 4096:
            continue
        body = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
        if body[:4] != b"PK\x03\x04":
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                names = set(zf.namelist())
                for dn, want in want_by_dn.items():
                    if dn in got:
                        continue
                    ep = f"{dn}/entry_points.txt"
                    if ep not in names:
                        continue
                    data = zf.read(ep)
                    if b64sha256(data) == want:
                        got[dn] = data
        except (zipfile.BadZipFile, UnicodeDecodeError, OSError):
            continue
    return got


def main() -> int:
    broken: dict[str, str] = {}  # dist-info 目录名 -> RECORD sha256
    for di in sorted(VENV_SP.glob("*.dist-info")):
        ep = di / "entry_points.txt"
        if ep.exists() and is_encrypted(ep):
            want = record_sha256(di)
            if want:
                broken[di.name] = want
            else:
                print(f"SKIP {di.name}: RECORD 不可读或无该文件记录，需重装")

    if not broken:
        print("all entry_points.txt OK")
        return 0

    fixed: list[str] = []
    missing: list[str] = []
    cache_hits = try_pip_cache(broken)
    for dn, want in broken.items():
        data = cache_hits.get(dn) or try_system_python(dn, want)
        if data is None:
            missing.append(dn)
            continue
        (VENV_SP / dn / "entry_points.txt").write_bytes(data)
        fixed.append(dn)

    print(f"fixed={len(fixed)}")
    for dn in fixed:
        print("  OK", dn)
    if missing:
        print(f"no-source={len(missing)}（联网后 pip install --force-reinstall --no-deps）")
        for dn in missing:
            print("  MISS", dn)
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
