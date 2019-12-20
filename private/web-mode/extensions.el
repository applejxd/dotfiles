;;; extensions.el --- web-mode Layer extensions File for Spacemacs
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

(setq web-mode-pre-extensions
      '(
        ;; pre extension names go here
        ))

(setq web-mode-post-extensions
      '(
        ;; post extension names go here
        (add-to-list 'auto-mode-alist '("\\.phtml\\'" . web-mode))
        (add-to-list 'auto-mode-alist '("\\.tpl\\.php\\'" . web-mode))
        (add-to-list 'auto-mode-alist '("\\.[gj]sp\\'" . web-mode))
        (add-to-list 'auto-mode-alist '("\\.as[cp]x\\'" . web-mode))
        (add-to-list 'auto-mode-alist '("\\.erb\\'" . web-mode))
        (add-to-list 'auto-mode-alist '("\\.mustache\\'" . web-mode))
        (add-to-list 'auto-mode-alist '("\\.djhtml\\'" . web-mode))
        (add-to-list 'auto-mode-alist '("\\.html?\\'" . web-mode))
        (setq web-mode-engines-alist
              '(("php"    . "\\.phtml\\'")
                ("blade"  . "\\.blade\\.")))
        ))

;; For each extension, define a function web-mode/init-<extension-name>
;;
;; (defun web-mode/init-my-extension ()
;;   "Initialize my extension"
;;   )
;;
;; Often the body of an initialize function uses `use-package'
;; For more info on `use-package', see readme:
;; https://github.com/jwiegley/use-package
