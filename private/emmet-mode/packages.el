;;; packages.el --- emmet-mode Layer packages File for Spacemacs
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
(setq emmet-mode-packages
    '(
      ;; package names go here
      emmet-mode
      ))

;; List of packages to exclude.
(setq emmet-mode-excluded-packages '())

;; For each package, define a function emmet-mode/init-<package-name>
;;
(defun emmet-mode/init-emmet-mode ()
  "Initialize my package"
  (use-package emmet-mode
    :config
    (add-hook 'sgml-mode-hook 'emmet-mode) ;; マークアップ言語全部で使う
    (add-hook 'css-mode-hook  'emmet-mode) ;; CSSにも使う
    (add-hook 'web-mode-hook  'emmet-mode) ;; Web-mode にも使う
    ;; indent はスペース4個
    (add-hook 'emmet-mode-hook (lambda () (setq emmet-indentation 4)))
    ;; C-c C-j で展開
    (define-key emmet-mode-keymap (kbd "C-c C-j") 'emmet-expand-line)
    )
  )
;;
;; Often the body of an initialize function uses `use-package'
;; For more info on `use-package', see readme:
;; https://github.com/jwiegley/use-package
