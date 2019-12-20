;;; packages.el --- yatex Layer packages File for Spacemacs
;;
;; Copyright (c) 2012-2014 Sylvain Benner
;; Copyright (c) 2014-2015 Sylvain Benner & Contributors
;;
;; Author: Sylvain Benner <sylvain.benner@gmail.com>
;; URL: https://github.com/syl20bnr/spacemacs
;;
;; This file is not part of GNU Emacs.
;;
;;; License: GPLv3

;; List of all packages to install and/or initialize. Built-in packages
;; which require an initialization must be listed explicitly in the list.
(setq yatex-packages
    '(
      ;; package names go here
      yatex
      ))

;; List of packages to exclude.
(setq yatex-excluded-packages '())

;; For each package, define a function yatex/init-<package-name>
;;
(defun yatex/init-yatex ()
  ;; "Initialize yatex"
  (use-package yatex
    :config
    ;;; ロードパス
    ;; (add-to-list 'load-path "~/.emacs.d/yatex")

    ;;; YaTeXモードで開くファイル
    (setq auto-mode-alist
      (append '(("\\.tex$" . yatex-mode)
                ("\\.ltx$" . yatex-mode)
                ("\\.cls$" . yatex-mode)
                ("\\.sty$" . yatex-mode)
                ("\\.clo$" . yatex-mode)
                ("\\.bbl$" . yatex-mode)) auto-mode-alist))
    (autoload 'yatex-mode "yatex" "Yet Another LaTeX mode" t)

    ;;; C-c [key] -> C-c C-[key] (recommended)
    (setq YaTeX-inhibit-prefix-letter t)

    ;;; ファイルの文字コードを変更せずに保存（デフォルト）
    (setq YaTeX-kanji-code nil)

    ;;; タイプセット log の文字コード
    (setq YaTeX-latex-message-code 'utf-8)

    ;;; use LaTeX2e and AMS-LaTeX（デフォルト）
    (setq YaTeX-use-LaTeX2e t)
    (setq YaTeX-use-AMS-LaTeX t)

    ;;; タイプセットコマンド
    ;;(setq tex-command "pdflatex")
    ;;(setq tex-command "~/.emacs.d/private/yatex/platex2pdf-utf8")
    (setq tex-command "latexmk -gg -pdfxe")

    ;;; Viewer の設定
    ;;; dvi2 -> after C-c C-t j, tex-pdf-view -> after C-c C-t d
    (setq YaTeX-dvi2-command-ext-alist
      '(("Preview\\|Skim\\|TeXShop" . ".pdf")))
    ;; (setq dvi2-command "open -a TeXShop")
    (setq dvi2-command "open -a Skim")
    (setq tex-pdfview-command "open -a Skim")

    ;;; 新規ファイル作成時に自動挿入するファイル名
    (setq YaTeX-template-file "~/.emacs.d/private/yatex/master.tex")
  )
)
;;
;; Often the body of an initialize function uses `use-package'
;; For more info on `use-package', see readme:
;; https://github.com/jwiegley/use-package
