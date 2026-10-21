"""vendor した imozuru のスクリプトに、この dotfiles 側の追加を当てる。

編集ツールの後処理の整形は上流との差分を大きくするので、文字列の置換をこのスクリプトで行う。
上流の原本に対して何度でも当て直せる (置換元が 1 つでなければ止まる)。
使い方 (リポジトリのルートで): 上流の 4 本を home/dot_claude/skills/imozuru/scripts/ へ複写し直してから
`python3 scripts/vendor/imozuru_patch.py`。
see docs/spec/imozuru.md#上流との差分
"""

from pathlib import Path

D = Path("home/dot_claude/skills/imozuru/scripts")


def head(*names: str, net: bool = False, pathlib: bool = False) -> str:
    lines = ["\n# この dotfiles 側の追加 (imozuru_root.py / imozuru_net.py)"]
    if pathlib:
        lines.append("from pathlib import Path")
    lines.append("sys.path.insert(0, str(Path(__file__).resolve().parent))")
    if net:
        lines.append("from imozuru_net import PinnedHTTPHandler, PinnedHTTPSHandler  # noqa: E402")
    lines.append(f"from imozuru_root import {', '.join(names)}  # noqa: E402")
    return "\n".join(lines) + "\n"


OPENER_OLD = "_OPENER = urllib.request.build_opener(_Redirect308)"
OPENER_NEW = (
    "_OPENER = urllib.request.build_opener(_Redirect308, PinnedHTTPHandler, PinnedHTTPSHandler)"
)

# YouTube は yt-dlp が自分で通信し、宛先を確かめられない。個人の PC (applejxd) の印がある機械で、確認の出る
# 別スクリプト fetch_youtube.py (許可に載せない) 経由のときだけ取る。fetch.py 自身は YouTube を通さない
YOUTUBE_OLD = '    if is_youtube(url):\n        if missing("yt-dlp"):'
YOUTUBE_NEW = (
    '    youtube_block = youtube_problem(globals().get("YOUTUBE_VIA_WRAPPER", False)) if is_youtube(url) else None\n'
    "    if youtube_block:\n"
    '        print(f"FAIL\\t{name}\\t{youtube_block}")\n'
    "        return 1\n" + YOUTUBE_OLD
)

PATCHES = {
    "fetch.py": [
        (
            "from pathlib import Path\n",
            "from pathlib import Path\n"
            + head("confine", "refuse_secrets", "youtube_problem", net=True),
        ),
        (OPENER_OLD, OPENER_NEW),
        (
            "sources, name, url = Path(sys.argv[1]), sys.argv[2], sys.argv[3]",
            'sources, name, url = confine(Path(sys.argv[1])), sys.argv[2], sys.argv[3]\n    refuse_secrets("URL", url)',
        ),
        (YOUTUBE_OLD, YOUTUBE_NEW),
        ('["yt-dlp", "--no-update",', '["yt-dlp", "--ignore-config", "--no-update",'),
        (
            "    with subprocess.Popen(cmd, **kwargs) as proc:",
            '    kwargs.setdefault("stdin", subprocess.DEVNULL)\n    with subprocess.Popen(cmd, **kwargs) as proc:',
        ),
    ],
    "report.py": [
        (
            "from pathlib import Path, PureWindowsPath\n",
            "from pathlib import Path, PureWindowsPath\n" + head("confine"),
        ),
        ("topic = Path(sys.argv[1]).expanduser()", "topic = confine(Path(sys.argv[1]))"),
    ],
    "watch.py": [
        (
            "from xml.parsers import expat\n",
            "from xml.parsers import expat\n"
            + head("confine", "refuse_secrets", "secret_reason", net=True),
        ),
        (OPENER_OLD, OPENER_NEW),
        # 見張る先の URL は外部のページが示したものを保存して、あとの check で送る。送る直前にも検査する
        (
            "    problem = url_problem(url)\n    if problem:\n        raise UnsafeURL(problem)\n"
            "    req = urllib.request.Request(url, headers=UA)",
            # 秘匿検査は名前を引く前 (url_problem はホスト名を引くので、名前に秘密があると DNS に載る)
            "    secret = secret_reason(url)\n    if secret:\n"
            '        raise UnsafeURL(f"URL に「{secret}」らしき文字列がある")\n'
            "    problem = url_problem(url)\n    if problem:\n        raise UnsafeURL(problem)\n"
            "    req = urllib.request.Request(url, headers=UA)",
        ),
        (
            "cmd, topic = args[0], Path(args[1]).expanduser()",
            "cmd, topic = args[0], confine(Path(args[1]))",
        ),
        (
            "        return cmd_add(topic, args[2], args[3] if len(args) > 3 else None)",
            '        refuse_secrets("フィードの URL", args[2])\n        return cmd_add(topic, args[2], args[3] if len(args) > 3 else None)',
        ),
    ],
    "chain.py": [
        (
            "import urllib.request\n",
            "import urllib.request\n" + head("refuse_secrets", pathlib=True),
        ),
        (
            '    cmd, key = args[0], " ".join(args[1:])',
            '    cmd, key = args[0], " ".join(args[1:])\n    refuse_secrets("検索語", key)',
        ),
    ],
}

for name, edits in PATCHES.items():
    path = D / name
    text = path.read_text(encoding="utf-8")
    for old, new in edits:
        if text.count(old) != 1:
            raise SystemExit(f"{name}: 置換元が 1 つではない: {old!r}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    print("patched", name)
