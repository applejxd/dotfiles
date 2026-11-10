"""YouTube の字幕を取る (個人の PC (applejxd) だけに配る。呼び出しごとに確認が出る)。

fetch.py は確認なしの許可に載るので、yt-dlp (自分で通信し、宛先をこちらで確かめられない) を使う YouTube の経路を
通さない。この別スクリプトは許可に載せないので、呼ぶたびに確認が出る。使い方は fetch.py と同じ。
会社の PC には、chezmoi がこのファイル自体を配らない (.chezmoiignore.tmpl)。
上流 (MaryCache/imozuru) には無い、この dotfiles 側の追加。see docs/spec/imozuru.md#youtube
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch

if __name__ == "__main__":
    fetch.YOUTUBE_VIA_WRAPPER = True
    sys.stdout.reconfigure(errors="replace")
    sys.exit(fetch.main())
