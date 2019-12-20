;;; packages.el --- smart-compile Layer packages File for Spacemacs
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
(setq smart-compile-packages
    '(
      ;; package names go here
			smart-compile
      ))

;; List of packages to exclude.
(setq smart-compile-excluded-packages '())

;; For each package, define a function smart-compile/init-<package-name>
;;
(defun smart-compile/init-smart-compile ()
  "Initialize smart-compile"
	(use-package smart-compile
    :config
    ;; ショートカットキー
    (global-set-key (kbd "C-x c") 'smart-compile)
    (global-set-key (kbd "C-x C-x") (kbd "C-x c C-m"))

    ;; smart-compile のコマンドをデフォルトから変更&追加
    (add-to-list 'smart-compile-alist '("\\.rb\\'" . "ruby %f"))
    (add-to-list 'smart-compile-alist '("\\.php\\'" . "php %f "))
    ;; (add-to-list 'smart-compile-alist '("\\.c\\'" . "gcc -O2 %f -lm -o %n && ./%n"))
    (add-to-list 'smart-compile-alist '("\\.c\\'" . "gcc -O2 -lgsl -lgslcblas %f -lm -o %n && ./%n"))

    ;; c++ のコンパイルコマンド.GSLオプション指定のあるものを使用.
    ;; -02 -> 最適化オプション, -std=c++11 -> c+11@2011 を使用, -lgsl -lgslcblas -> GSLオプション
    ;; -lm -> 算術演算関数使用, -o -> オブジェクトファイルをリンク
    ;; && ./%n -> 即時実行
    ;; (add-to-list 'smart-compile-alist '("\\.[Cc]+[Pp]*\\'" . "g++ -O2 -std=c++11 %f -o %n && ./%n"))
    (add-to-list 'smart-compile-alist '("\\.cpp\\'" . "g++ -O2 -std=c++11 -lgsl -lgslcblas -lm %f -o %n && ./%n"))

    (add-to-list 'smart-compile-alist '("\\.awk\\'" . "awk -f %f "))
    (add-to-list 'smart-compile-alist '("\\.ts\\'" . "tsc -d %f"))

    ))
;;
;; Often the body of an initialize function uses `use-package'
;; For more info on `use-package', see readme:
;; https://github.com/jwiegley/use-package
