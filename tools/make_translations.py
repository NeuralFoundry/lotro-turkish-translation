"""Build translations/*.tsv (key<TAB>turkish) from translation memory files (english<TAB>turkish).

usage: python tools/make_translations.py <tm folder> [--game <folder with an untranslated client_local_English.dat>]

tm files p1_*, p2_*, p3_* and u_* become 1-interface.tsv, 2-short-texts.tsv, 3-long-texts.tsv
and 4-game-updates.tsv (text added by game updates).
The key is a hash of the English text (lotro_tr.text_key), so the repository holds no game text.
With --game every English string of the game is hashed as well, to prove no two strings share a key.
"""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
from lotro_tr import NAME, text_key  # noqa: E402
from dat_archive import Archive  # noqa: E402
from text_table import parse  # noqa: E402

GROUPS = (("p1_", "1-interface.tsv"), ("p2_", "2-short-texts.tsv"), ("p3_", "3-long-texts.tsv"),
          ("u_", "4-game-updates.tsv"))
TM_HEADER = "# english\tturkish"


def read_tm(path):
    for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        # English text may itself start with '#' ("#-1:{0} ..."); only tab-less lines are comments
        if not line.strip() or line == TM_HEADER or (line.startswith("#") and "\t" not in line):
            continue
        en, sep, tr = line.partition("\t")
        if not sep or not tr.strip():
            raise SystemExit(f"{path.name}:{n}: expected 'english<TAB>turkish'")
        yield en, tr


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tm", type=Path)
    p.add_argument("--game", type=Path)
    p.add_argument("--out", type=Path, default=ROOT / "translations")
    args = p.parse_args()

    owner = {}          # key -> English, to catch collisions
    translation = {}    # English -> Turkish, to catch conflicts between files
    written = set()     # English already in an earlier output file
    leftover = {p.name for p in args.tm.glob("*.tsv")}
    args.out.mkdir(exist_ok=True)
    for prefix, out_name in GROUPS:
        rows = {}
        for path in sorted(args.tm.glob(prefix + "*.tsv")):
            leftover.discard(path.name)
            for en, tr in read_tm(path):
                if translation.setdefault(en, tr) != tr:
                    raise SystemExit(f"{path.name}: conflicting translation for {en!r}")
                key = text_key(en)
                if owner.setdefault(key, en) != en:
                    raise SystemExit(f"key collision {key}: {owner[key]!r} / {en!r}")
                if en not in written:
                    rows[key] = tr
        written.update(owner[k] for k in rows)
        with (args.out / out_name).open("w", encoding="utf-8", newline="\n") as f:
            f.write("# key\tturkish\n")
            f.writelines(f"{k}\t{rows[k]}\n" for k in sorted(rows))
        print(f"{out_name}: {len(rows)} translations")
    if leftover:
        raise SystemExit(f"tm files outside p1_/p2_/p3_/u_: {sorted(leftover)[:10]}")

    if args.game:
        archive = Archive(args.game / NAME)
        strings = set()
        for did in [e[1] for e in archive.entries() if e[1] >> 24 == 0x25]:
            strings.update(r.template() for r in parse(archive.decoded(did)).records)
        for en in strings:
            if owner.setdefault(text_key(en), en) != en:
                raise SystemExit(f"key collision {text_key(en)}: {owner[text_key(en)]!r} / {en!r}")
        print(f"no key collisions among {len(owner)} strings ({len(strings)} in the game)")


if __name__ == "__main__":
    main()
