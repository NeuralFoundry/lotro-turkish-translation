"""Assemble the release ZIP: launchers, installer, translations and the official embedded Python.

usage: python tools/build_release.py <python-X.Y.Z-embed-amd64.zip> [--out dist/LOTRO-Turkce.zip]

The ZIP unpacks to one folder, LOTRO-Turkce, with Kur.cmd next to python/, app/ and translations/.
"""
from pathlib import Path
import argparse
import time
import zipfile

ROOT = Path(__file__).resolve().parent.parent
TOP = "LOTRO-Turkce"
FILES = ["Kur.cmd", "Kaldir.cmd", "OKU-BENI.txt", "LICENSE",
         "app/lotro_tr.py", "app/dat_archive.py", "app/text_table.py"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("python", type=Path, help="python-X.Y.Z-embed-amd64.zip from python.org")
    p.add_argument("--out", type=Path, default=ROOT / "dist" / "LOTRO-Turkce.zip")
    args = p.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.localtime()[:6]

    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        def add(name, data):
            info = zipfile.ZipInfo(f"{TOP}/{name}", stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)

        for name in FILES:
            data = (ROOT / name).read_bytes()
            if name.endswith((".cmd", ".txt")):     # cmd.exe needs CRLF; old Notepad does too
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            add(name, data)
        for path in sorted((ROOT / "translations").glob("*.tsv")):
            add(f"translations/{path.name}", path.read_bytes())
        with zipfile.ZipFile(args.python) as py:
            for info in py.infolist():
                if not info.is_dir():
                    add(f"python/{info.filename}", py.read(info))
    print(f"{args.out} ({args.out.stat().st_size / 2**20:.1f} MB)")


if __name__ == "__main__":
    main()
