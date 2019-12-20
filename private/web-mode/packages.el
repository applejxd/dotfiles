;;; packages.el --- web-mode Layer packages File for Spacemacs
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
(setq web-mode-packages
      '(
        ;; package names go here
        web-mode
        ))

;; List of packages to exclude.
(setq web-mode-excluded-packages '())

;; For each package, define a function web-mode/init-<package-name>
;;
(defun web-mode/init-web-mode ()
  "Initialize my package"
  (use-package web-mode
    :config
    ;; 適用する拡張子
    (add-to-list 'auto-mode-alist '("\\.jsp$"       . web-mode))
    (add-to-list 'auto-mode-alist '("\\.as[cp]x$"   . web-mode))
    (add-to-list 'auto-mode-alist '("\\.erb$"       . web-mode))
    (add-to-list 'auto-mode-alist '("\\.html?$"     . web-mode))
    (add-to-list 'auto-mode-alist '("\\.phtml$"     . web-mode))
    (add-to-list 'auto-mode-alist '("\\.tpl\\.php$" . web-mode))
    (add-to-list 'auto-mode-alist '("\\.css?$"     . web-mode))
    ;; インデント設定
    (setq web-mode-markup-indent-offset 4)
    )
  )
;;
;; Often the body of an initialize function uses `use-package'
;; For more info on `use-package', see readme:
;; https://github.com/jwiegley/use-package
