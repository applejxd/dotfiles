﻿# -*- mode: python; coding: utf-8-with-signature-dos -*-

####################################################################################################
## Emacs をターミナルで動かす場合に event-apply-modifier を使ってキーの置き換えを行う
####################################################################################################

try:
    # 設定されているか？
    fc.emacs_terminal
except:
    # 本機能を適用するターミナルを指定する
    # （ターミナルは、プロセス名称のみ（ワイルドカード指定可）、もしくは、プロセス名称、クラス名称、
    #   ウィンドウタイトルのリスト（ワイルドカード指定可、リストの後ろの項目から省略可）を指定して
    #   ください）
    fc.emacs_terminal = ["ubuntu*.exe",
                         "WindowsTerminal.exe",
                         [None, None,  "さくらのクラウドシェル*"],
                         ]

try:
    # 設定されているか？
    fc.emacs_replace_key
except:
    # 置きかえるるキーの組み合わせ（置き換え元、置き換え先の順）を指定する
    # （置き換え先には、event-apply-modifier の機能で置き換えるキーを指定してください）
    fc.emacs_replace_key = [["C-;", "C-x @ c ;"],
                            ]

# --------------------------------------------------------------------------------------------------

def is_emacs_terminal(window):
    global emacs_terminal_status

    if window is not fakeymacs.last_window:
        if any(checkWindow(*app, window=window) if type(app) is list else
               checkWindow( app, window=window) for app in fc.emacs_terminal):
            emacs_terminal_status = True
        else:
            emacs_terminal_status = False

    return emacs_terminal_status

keymap_et = keymap.defineWindowKeymap(check_func=is_emacs_terminal)

for key1, key2 in fc.emacs_replace_key:
    define_key(keymap_et, key1, self_insert_command4(*key2.split()))
