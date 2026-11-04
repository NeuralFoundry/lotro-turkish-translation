"""Turkish translation installer for The Lord of the Rings Online.

Changes only client_local_English.dat. Translated text tables and the directory nodes that
lead to them are appended after the original end of the file; the header gets a new file
size and directory root. Uninstall restores the old header and cuts the appended data off.
Both directions are verified with a full-file SHA-256.

  lotro_tr.py install      game and launcher must be closed
  lotro_tr.py uninstall
  lotro_tr.py status
  lotro_tr.py check        read-only: what install would change
  lotro_tr.py find         list the game folders found on this PC
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import argparse
import collections
import ctypes
from ctypes import wintypes as w
import hashlib
import itertools
import json
import msvcrt
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import traceback
import uuid
import winreg

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))    # the embedded Python does not put the script folder on sys.path
from dat_archive import HEADER_SIZE, Archive, Plan  # noqa: E402
from text_table import FormatError, parse, serialize, split_template  # noqa: E402

VERSION = "1.0.1"
ROOT = APP.parent
TRANSLATIONS = ROOT / "translations"
REMEMBERED = ROOT / "game_folder.txt"
NAME = "client_local_English.dat"
STATE_DIR = "LOTRO-Turkce"      # inside the game folder: active.json and one folder per install
CHUNK = 8 * 1024 * 1024
KEY = re.compile(r"[0-9a-f]{16}$")
MARKUP = re.compile(r"<(?:/|\\+)?(?:rgb|u|li|b|i|br|body|h1|font|select|examine|examineia|examineiteminstance)\b[^>]*>",
                    re.I)
BIND = re.compile(r"#-?\d+:\{\d+\}")
CHOICE = re.compile(r"#-?\d+:")
GRAMMAR_TAG = re.compile(r"\[[A-Za-z]+\]$")
KEYWORD = re.compile(r"^[a-z][a-z0-9_]*(,[a-z0-9_]+)*$")
GAME_PROCESSES = {"lotroclient.exe", "lotroclient64.exe", "lotrolauncher.exe", "turbinelauncher.exe"}
COMMON_FOLDERS = [r"The Lord of the Rings Online",
                  r"Program Files (x86)\StandingStoneGames\The Lord of the Rings Online",
                  r"Program Files\StandingStoneGames\The Lord of the Rings Online",
                  r"Program Files (x86)\Turbine\The Lord of the Rings Online",
                  r"Games\The Lord of the Rings Online",
                  r"SteamLibrary\steamapps\common\Lord of the Rings Online"]

K = ctypes.WinDLL("kernel32", use_last_error=True)
K.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
K.CreateFileW.restype = w.HANDLE
K.CloseHandle.argtypes = [w.HANDLE]
K.SetFilePointerEx.argtypes = [w.HANDLE, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong), w.DWORD]
K.SetFilePointerEx.restype = w.BOOL
K.SetEndOfFile.argtypes = [w.HANDLE]
K.SetEndOfFile.restype = w.BOOL
K.GetLogicalDrives.restype = w.DWORD
K.GetDriveTypeW.argtypes = [w.LPCWSTR]
K.GetDriveTypeW.restype = w.UINT
SHELL = ctypes.WinDLL("shell32")
SHELL.ShellExecuteW.argtypes = [w.HWND, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, ctypes.c_int]
SHELL.ShellExecuteW.restype = ctypes.c_ssize_t


class Fail(Exception):
    """A problem the user can fix; shown without a traceback."""


def num(n):
    return f"{n:,}".replace(",", ".")


def text_key(english):
    """Translations are keyed by a hash of the English text, so the game's own text is not redistributed."""
    return hashlib.blake2b(english.encode("utf-8"), digest_size=8).hexdigest()


# ---------------------------------------------------------------- files
def journal_save(path, value):
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def durable_bytes(path, data):
    with path.open("xb", buffering=0) as f:
        if f.write(data) != len(data):
            raise OSError("Short transaction artifact write")
        os.fsync(f.fileno())


@contextmanager
def exclusive(path):
    handle = K.CreateFileW(str(path), 0xC0000000, 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error == 5:
            raise PermissionError(error, "Access denied", str(path))
        if error in (32, 33):
            raise Fail("Oyun dosyası başka bir program tarafından kullanılıyor. "
                       "Oyunu ve başlatıcıyı tamamen kapatıp tekrar deneyin.")
        raise ctypes.WinError(error)
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_BINARY | os.O_RDWR)
    except BaseException:
        K.CloseHandle(handle)
        raise
    with os.fdopen(fd, "r+b", buffering=0) as f:
        yield f


def require_game_closed():
    result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=True)
    names = {line.split(",", 1)[0].strip('"').lower() for line in result.stdout.splitlines()}
    busy = names & GAME_PROCESSES
    if busy:
        raise Fail("Oyun ya da başlatıcı açık (" + ", ".join(sorted(busy)) + "). "
                   "Tamamen kapatıp tekrar deneyin.")


def resize(f, size):
    f.flush()
    handle = msvcrt.get_osfhandle(f.fileno())
    if not K.SetFilePointerEx(handle, size, None, 0) or not K.SetEndOfFile(handle):
        raise ctypes.WinError(ctypes.get_last_error())
    f.seek(0)


def stream_hash(f, header=None, end=None, tail=b""):
    h = hashlib.sha256()
    if header is not None:
        h.update(header)
        f.seek(HEADER_SIZE)
    else:
        f.seek(0)
    remaining = None if end is None else end - f.tell()
    while remaining is None or remaining:
        buf = f.read(CHUNK if remaining is None else min(CHUNK, remaining))
        if not buf:
            if remaining:
                raise ValueError("Truncated hash range")
            break
        h.update(buf)
        if remaining is not None:
            remaining -= len(buf)
    h.update(tail)
    return h.hexdigest()


# ---------------------------------------------------------------- finding the game
def registry_folders():
    out = []
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                       (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                       (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")):
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            for i in itertools.count():
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                try:
                    with winreg.OpenKey(root, sub) as k:
                        if "lord of the rings online" in str(winreg.QueryValueEx(k, "DisplayName")[0]).lower():
                            out.append(Path(winreg.QueryValueEx(k, "InstallLocation")[0]))
                except OSError:
                    pass
    return out


def steam_folders():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        return []
    libraries = [steam]
    try:
        vdf = (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        libraries += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf)]
    except OSError:
        pass
    return [lib / "steamapps" / "common" / "Lord of the Rings Online" for lib in libraries]


def fixed_drives():
    mask = K.GetLogicalDrives()
    for i in range(26):
        root = chr(65 + i) + ":\\"
        if mask >> i & 1 and K.GetDriveTypeW(root) == 3:
            yield Path(root)


def find_games():
    found, seen = [], set()
    candidates = registry_folders() + steam_folders() + [d / c for d in fixed_drives() for c in COMMON_FOLDERS]
    try:
        candidates.insert(0, Path(REMEMBERED.read_text(encoding="utf-8").strip()))
    except OSError:
        pass
    for folder in candidates:
        try:
            if not (folder / NAME).is_file():
                continue
            key = os.path.normcase(str(folder.resolve()))
        except OSError:
            continue
        if key not in seen:
            seen.add(key)
            found.append(folder.resolve())
    return found


def as_game_folder(text):
    folder = Path(text.strip().strip('"').strip())
    if folder.is_file():            # the dat or the launcher was dragged in instead of the folder
        folder = folder.parent
    if not (folder / NAME).is_file():
        raise Fail(f"Bu klasörde {NAME} bulunamadı: {folder}")
    return folder.resolve()


def ask(prompt):
    try:
        return input(prompt)
    except EOFError:
        raise Fail("Oyun klasörü seçilemedi. Klasörü --game ile belirtin.")


def choose_game(given, want_installed):
    if given:
        return as_game_folder(given)
    found = find_games()
    if want_installed:
        installed = [g for g in found if (g / STATE_DIR / "active.json").exists()]
        found = installed or found
    if len(found) == 1:
        return found[0]
    if found:
        print("Birden fazla oyun klasörü bulundu:")
        for i, g in enumerate(found, 1):
            print(f"  {i}) {g}")
        while True:
            answer = ask("Hangisi? Numarasını yazıp Enter'a basın: ").strip()
            if answer.isdigit() and 1 <= int(answer) <= len(found):
                return found[int(answer) - 1]
    print("Oyun klasörü otomatik bulunamadı.")
    print("Oyunun klasörünü (içinde LotroLauncher.exe olan klasör) bu pencereye sürükleyip Enter'a basın.")
    while True:
        answer = ask("> ")
        if not answer.strip():
            continue
        try:
            return as_game_folder(answer)
        except Fail as e:
            print(e)


def remember(folder):
    try:
        REMEMBERED.write_text(str(folder), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------- translations
def load_translations(folder):
    files = sorted(Path(folder).glob("*.tsv"))
    if not files:
        raise Fail(f"Çeviri dosyaları bulunamadı ({folder}). ZIP dosyasının tamamını çıkardığınızdan emin olun.")
    tm = {}
    for path in files:
        for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line or line.startswith("#"):
                continue
            key, sep, tr = line.partition("\t")
            if not sep or not KEY.match(key) or not tr.strip():
                raise Fail(f"{path.name}, satır {n}: beklenen biçim 'anahtar<TAB>çeviri'")
            if tm.get(key, tr) != tr:
                raise Fail(f"{path.name}, satır {n}: aynı metin için iki farklı çeviri")
            tm[key] = tr
    return tm


def check_markup(en, tr):
    if sorted(MARKUP.findall(en)) != sorted(MARKUP.findall(tr)):
        raise FormatError("markup tags differ (<rgb>, <u>, <li>, <b>, link tags)")
    if sorted(BIND.findall(en)) != sorted(BIND.findall(tr)):
        raise FormatError("#N:{n} bindings differ")
    extra = collections.Counter(CHOICE.findall(tr)) - collections.Counter(CHOICE.findall(en))
    if extra:
        raise FormatError("#N: markers not in the English: %s" % sorted(extra))
    tag = GRAMMAR_TAG.search(en)
    if tag and not tr.endswith(tag.group(0)):
        raise FormatError("grammar tag %s missing at end" % tag.group(0))


def protected(table):
    """Records that must stay English: keywords (chat commands, emotes, name-generator syllables) and <DNT>."""
    keywords = [r for r in table.records if KEYWORD.match(r.template())]
    out = set()
    if len(keywords) >= 8 and len(keywords) >= 0.3 * len(table.records):
        out = {id(r) for r in keywords}
    return out | {id(r) for r in table.records if "<DNT>" in r.template()}


def build(archive, tm):
    plan = Plan(archive)
    report = {"tables": 0, "records": 0, "untranslated": 0, "protected": 0, "skipped": []}
    expected = {}
    for did in [e[1] for e in archive.entries() if e[1] >> 24 == 0x25]:
        table = parse(archive.decoded(did))
        keep = protected(table)
        changed = 0
        for r in table.records:
            if id(r) in keep:
                report["protected"] += 1
                continue
            en = r.template()
            tr = tm.get(text_key(en))
            if tr is None:
                report["untranslated"] += 1
                continue
            try:
                check_markup(en, tr)
                r.pieces = split_template(tr, len(r.args))
            except FormatError as e:    # leave that one string English rather than break the game
                report["skipped"].append(f"{did:08x}/{r.token:08x}: {e}")
                continue
            changed += 1
        if changed:
            data = serialize(table)
            plan.add_record(did, data, archive.find(did), replace=True)
            expected[did] = data
            report["tables"] += 1
            report["records"] += changed
    header, tail, _ = plan.finish()
    report["append_bytes"] = len(tail)
    return header, tail, expected, report


# ---------------------------------------------------------------- install / uninstall
def active_transaction(state):
    sf = state / "active.json"
    if not sf.exists():
        return None
    return state / json.loads(sf.read_text(encoding="utf-8"))["transaction"]


def base_archive(dat, state):
    """The archive as it was before our install: the old header still describes the untouched body."""
    a = Archive(dat)
    tdir = active_transaction(state)
    if tdir and (tdir / "header.new").exists() and a.header == (tdir / "header.new").read_bytes():
        a.header = (tdir / "header.old").read_bytes()
        a.size = struct.unpack_from("<I", a.header, 0x148)[0]
        a.root = struct.unpack_from("<I", a.header, 0x160)[0]
        a.cache = {}
    return a


def restore(f, tdir, j):
    """Undo one transaction, also a half-written one; refuses if anything but this patch changed the file."""
    old_header = (tdir / "header.old").read_bytes()
    new_header = (tdir / "header.new").read_bytes()
    tail = (tdir / "tail.bin").read_bytes()
    f.seek(0, 2)
    size = f.tell()
    if not j["before_size"] <= size <= j["before_size"] + len(tail):
        raise ValueError("file size changed since install (game update?)")
    f.seek(0)
    current = f.read(HEADER_SIZE)
    if not all(c in (a, b) for c, a, b in zip(current, old_header, new_header)):
        raise ValueError("header changed since install (game update?)")
    if stream_hash(f, header=old_header, end=j["before_size"]) != j["before_sha256"]:
        raise ValueError("file body changed since install (game update?)")
    f.seek(j["before_size"])
    if f.read() != tail[:size - j["before_size"]]:
        raise ValueError("appended data is not this patch")
    f.seek(0)
    if f.write(old_header) != HEADER_SIZE:
        raise OSError("Short header write")
    resize(f, j["before_size"])
    f.flush()
    os.fsync(f.fileno())
    if stream_hash(f) != j["before_sha256"]:
        raise ValueError("restored file hash mismatch")


def rollback_active(dat, state):
    """Undo the recorded install. Returns 'none', 'restored' or 'superseded' (the game changed the file since)."""
    tdir = active_transaction(state)
    if tdir is None:
        return "none"
    result = "superseded"
    if (tdir / "transaction.json").exists():
        j = json.loads((tdir / "transaction.json").read_text(encoding="utf-8"))
        with exclusive(dat) as f:
            try:
                restore(f, tdir, j)
                result = "restored"
            except ValueError:
                pass
    (state / "active.json").unlink()
    shutil.rmtree(tdir, ignore_errors=True)
    return result


def apply(dat, state, tm):
    tdir = state / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    with exclusive(dat) as f:
        a = Archive(handle=f)
        entries_before = len(a.entries())
        print("Oyun metinleri çevirilerle eşleştiriliyor...", flush=True)
        header, tail, expected, report = build(a, tm)
        if not expected:
            raise Fail("Bu oyun dosyasında çevrilecek İngilizce metin bulunamadı. "
                       "Oyun dilinin English olduğundan emin olun; çeviri zaten kurulu da olabilir.")
        need = 2 * len(tail) + (64 << 20)
        if shutil.disk_usage(state).free < need:
            raise Fail(f"Oyunun bulunduğu sürücüde yeterli boş alan yok. En az {need >> 20} MB gerekiyor.")
        print("Oyun dosyası kontrol ediliyor...", flush=True)
        before = stream_hash(f)
        tdir.mkdir()
        durable_bytes(tdir / "header.old", a.header)
        durable_bytes(tdir / "header.new", header)
        durable_bytes(tdir / "tail.bin", tail)
        j = {"schema": 1, "status": "APPLYING", "version": VERSION,
             "installed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
             "before_size": a.size, "before_sha256": before,
             "after_sha256": stream_hash(f, header=header, tail=tail), "report": report}
        journal_save(tdir / "transaction.json", j)
        # recorded before the first write, so even an interrupted install can be undone next time
        journal_save(state / "active.json", {"transaction": tdir.name})
        try:
            print("Türkçe metinler yazılıyor...", flush=True)
            f.seek(a.size)
            if f.write(tail) != len(tail):
                raise OSError("Short append write")
            f.flush()
            os.fsync(f.fileno())
            f.seek(0)
            if f.write(header) != HEADER_SIZE:
                raise OSError("Short header write")
            f.flush()
            os.fsync(f.fileno())
            print("Yazılanlar doğrulanıyor...", flush=True)
            if stream_hash(f) != j["after_sha256"]:
                raise ValueError("patched file hash mismatch")
            b = Archive(handle=f)
            if len(b.entries()) != entries_before:
                raise ValueError("directory entry count changed")
            for did, data in expected.items():
                if b.decoded(did) != data:
                    raise ValueError(f"table {did:08x} reads back wrong")
        except BaseException as error:
            j["status"], j["error"] = "ROLLING_BACK", str(error)
            journal_save(tdir / "transaction.json", j)
            restore(f, tdir, j)
            (state / "active.json").unlink()
            shutil.rmtree(tdir, ignore_errors=True)
            raise
    j["status"] = "APPLIED"
    journal_save(tdir / "transaction.json", j)
    return report


def install(dat, state, translations):
    print("Çeviriler yükleniyor...", flush=True)
    tm = load_translations(translations)
    state.mkdir(exist_ok=True)
    previous = rollback_active(dat, state)
    if previous == "restored":
        print("Önceki kurulum kaldırıldı, yenisi yapılıyor.")
    elif previous == "superseded":
        print("Oyun önceki kurulumdan sonra güncellenmiş; yeni kurulum güncel dosyaya yapılıyor.")
    report = apply(dat, state, tm)
    print()
    print(f"Kurulum tamamlandı. {num(report['records'])} metin Türkçe.")
    if report["skipped"]:
        print(f"{num(len(report['skipped']))} metin biçim uyuşmadığı için İngilizce bırakıldı.")
    print("Oyunu her zamanki gibi başlatabilirsiniz. Kaldırmak isterseniz Kaldir.cmd dosyasını çalıştırın.")


def uninstall(dat, state):
    result = rollback_active(dat, state) if state.exists() else "none"
    if result == "none":
        print("Türkçe çeviri kurulu değil; yapılacak bir şey yok.")
    elif result == "restored":
        print("Türkçe çeviri kaldırıldı. Oyun dosyası kurulumdan önceki haline birebir döndü.")
    else:
        print("Oyun, çeviri kurulduktan sonra güncellendiği için çeviri otomatik kaldırılamadı.")
        print("İngilizceye dönmek için Steam'de oyunun dosyalarını doğrulayın; Steam dışında oyunu yeniden kurun.")
    try:
        state.rmdir()
    except OSError:
        pass


def status(dat, state):
    tdir = active_transaction(state)
    if tdir is None or not (tdir / "transaction.json").exists():
        print("Türkçe çeviri kurulu değil.")
        return
    j = json.loads((tdir / "transaction.json").read_text(encoding="utf-8"))
    with dat.open("rb") as f:
        current = f.read(HEADER_SIZE)
    if j["status"] != "APPLIED":
        print("Yarım kalmış bir kurulum var. Kur.cmd ya da Kaldir.cmd dosyasını çalıştırın.")
    elif current != (tdir / "header.new").read_bytes():
        print("Çeviri kurulmuş, ama oyun o zamandan beri güncellenmiş. Kur.cmd dosyasını tekrar çalıştırın.")
    else:
        print(f"Türkçe çeviri kurulu: sürüm {j.get('version', '?')}, {j['installed_at'][:16].replace('T', ' ')}, "
              f"{num(j['report']['records'])} metin.")


# ---------------------------------------------------------------- main
def is_admin():
    try:
        return bool(SHELL.IsUserAnAdmin())
    except OSError:
        return False


def relaunch_as_admin(game):
    argv = sys.argv[1:]
    if not any(a == "--game" or a.startswith("--game=") for a in argv):
        argv += ["--game", str(game)]
    params = subprocess.list2cmdline((["-I"] if sys.flags.isolated else []) + [str(Path(__file__).resolve())] + argv)
    return SHELL.ShellExecuteW(None, "runas", sys.executable, params, None, 1) > 32


def run(args):
    if args.command == "find":
        for g in find_games():
            print(g)
        return 0
    print(f"LOTRO Türkçe Yama {VERSION}")
    print()
    game = choose_game(args.game, want_installed=args.command in ("uninstall", "status"))
    dat, state = game / NAME, game / STATE_DIR
    print(f"Oyun klasörü: {game}")
    if args.command == "status":
        status(dat, state)
        return 0
    if args.command == "check":
        print(json.dumps(build(base_archive(dat, state), load_translations(args.translations))[3],
                         indent=2, ensure_ascii=False))
        return 0
    if not args.no_process_check:
        require_game_closed()
    started = time.monotonic()
    try:
        if args.command == "install":
            install(dat, state, args.translations)
        else:
            uninstall(dat, state)
    except PermissionError:
        if is_admin() or args.no_elevate:
            raise Fail("Oyun klasörüne yazma izni yok. Dosyaya sağ tıklayıp 'Yönetici olarak çalıştır' deyin.")
        remember(game)
        print("Oyun klasörüne yazmak için yönetici izni gerekiyor. Windows'un sorusuna Evet deyin;")
        print("işlem açılacak yeni pencerede devam edecek.")
        if not relaunch_as_admin(game):
            raise Fail("Yönetici izni verilmedi. Tekrar denemek için dosyayı yeniden çalıştırın.")
        return None     # the elevated window takes over; this one closes without waiting
    remember(game)
    print(f"({time.monotonic() - started:.0f} saniye sürdü)")
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("install", "uninstall", "status", "check", "find"))
    p.add_argument("--game", help="game folder; found automatically when left out")
    p.add_argument("--translations", type=Path, default=TRANSLATIONS, help="folder of translation .tsv files")
    p.add_argument("--no-pause", action="store_true", help="do not wait for Enter at the end")
    p.add_argument("--no-elevate", action="store_true", help="fail instead of asking for administrator rights")
    p.add_argument("--no-process-check", action="store_true", help="only for test copies of the game file")
    args = p.parse_args()
    try:
        code = run(args)
    except Fail as e:
        print("\nHATA: " + str(e))
        code = 1
    except KeyboardInterrupt:
        print("\nİptal edildi.")
        code = 1
    except Exception:
        traceback.print_exc()
        print("\nBeklenmeyen bir hata oluştu. Bu pencerenin ekran görüntüsünü GitHub'daki Issues bölümüne "
              "gönderebilirsiniz.")
        code = 1
    if code is None:
        sys.exit(0)
    if not args.no_pause:
        try:
            input("\nPencereyi kapatmak için Enter'a basın...")
        except EOFError:
            pass
    sys.exit(code)


if __name__ == "__main__":
    main()
