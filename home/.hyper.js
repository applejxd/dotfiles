// Future versions of Hyper may add additional config options,

// which will not automatically be merged into this file.
// See https://hyper.is#cfg for all currently supported options.

module.exports = {
  config: {
    // choose either `'stable'` for receiving highly polished,
    // or `'canary'` for less polished but more frequent updates
    updateChannel: 'stable',

    // default font size in pixels for all tabs
    fontSize: 14,

    // font family with optional fallbacks
    fontFamily: '"Hack Nerd Font", Menlo, "DejaVu Sans Mono", Consolas, "Lucida Console", monospace',

    // default font weight: 'normal' or 'bold'
    fontWeight: 'normal',

    // font weight for bold characters: 'normal' or 'bold'
    fontWeightBold: 'bold',

    // line height as a relative unit
    lineHeight: 1,

    // letter spacing as a relative unit
    letterSpacing: 0,

    // terminal cursor background color and opacity (hex, rgb, hsl, hsv, hwb or cmyk)
    cursorColor: 'rgba(248,28,229,0.8)',

    // terminal text color under BLOCK cursor
    cursorAccentColor: '#000',

    // `'BEAM'` for |, `'UNDERLINE'` for _, `'BLOCK'` for █
    cursorShape: 'BLOCK',

    // set to `true` (without backticks and without quotes) for blinking cursor
    cursorBlink: false,

    // color of the text
    foregroundColor: '#fff',

    // terminal background color
    // opacity is only supported on macOS
    backgroundColor: '#000',

    // terminal selection color
    selectionColor: 'rgba(248,28,229,0.3)',

    // border color (window, tabs)
    borderColor: '#333',

    // custom CSS to embed in the main window
    // for status bar
    css: '.line { margin-bottom: 12px; font-size: 15px; font-weight: normal;}',

    // custom CSS to embed in the terminal window
    termCSS: '',

    // if you're using a Linux setup which show native menus, set to false
    // default: `true` on Linux, `true` on Windows, ignored on macOS
    showHamburgerMenu: '',

    // set to `false` (without backticks and without quotes) if you want to hide the minimize, maximize and close buttons
    // additionally, set to `'left'` if you want them on the left, like in Ubuntu
    // default: `true` (without backticks and without quotes) on Windows and Linux, ignored on macOS
    showWindowControls: '',

    // custom padding (CSS format, i.e.: `top right bottom left`)
    // padding: '12px 14px 18px 14px',
    padding: '5px 20px 25px 20px',

    // the full list. if you're going to provide the full color palette,
    // including the 6 x 6 color cubes and the grayscale map, just provide
    // an array here instead of a color map object
    colors: {
      black: '#000000',
      red: '#C51E14',
      green: '#1DC121',
      yellow: '#C7C329',
      blue: '#0A2FC4',
      magenta: '#C839C5',
      cyan: '#20C5C6',
      white: '#C7C7C7',
      lightBlack: '#686868',
      lightRed: '#FD6F6B',
      lightGreen: '#67F86F',
      lightYellow: '#FFFA72',
      lightBlue: '#6A76FB',
      lightMagenta: '#FD7CFC',
      lightCyan: '#68FDFE',
      lightWhite: '#FFFFFF',
    },

    // the shell to run when spawning a new session (i.e. /usr/local/bin/fish)
    // if left empty, your system's login shell will be used by default
    //
    // Windows
    // - Make sure to use a full path if the binary name doesn't work
    // - Remove `--login` in shellArgs
    //
    // Bash on Windows
    // - Example: `C:\\Windows\\System32\\bash.exe`
    //
    // PowerShell on Windows
    // - Example: `C:\\WINDOWS\\System32\\WindowsPowerShell\\v1.0\\powershell.exe`
    shell: '',

    // for setting shell arguments (i.e. for using interactive shellArgs: `['-i']`)
    // by default `['--login']` will be used
    shellArgs: ['--login'],

    // for environment variables
    env: {},

    // set to `false` for no bell
    bell: 'SOUND',

    // if `true` (without backticks and without quotes), selected text will automatically be copied to the clipboard
    copyOnSelect: false,

    // if `true` (without backticks and without quotes), hyper will be set as the default protocol client for SSH
    defaultSSHApp: true,

    // if `true` (without backticks and without quotes), on right click selected text will be copied or pasted if no
    // selection is present (`true` by default on Windows and disables the context menu feature)
    quickEdit: false,

    // choose either `'vertical'`, if you want the column mode when Option key is hold during selection (Default)
    // or `'force'`, if you want to force selection regardless of whether the terminal is in mouse events mode
    // (inside tmux or vim with mouse mode enabled for example).
    macOptionSelectionMode: 'vertical',

    // URL to custom bell
    // bellSoundURL: 'http://example.com/bell.mp3',

    // Whether to use the WebGL renderer. Set it to false to use canvas-based
    // rendering (slower, but supports transparent backgrounds)
    webGLRenderer: true,

    // for advanced config flags please refer to https://hyper.is/#cfg

    // Use Alt key as Meta key
    modifierKeys: { altIsMeta: true },

    // see http://bit.ly/2PCAErV
    overlay: {
      // ホットキー
      hotkeys: ['Control+;'],
      // 配置
      position: 'top',
      alwaysOnTop: false,
      primaryDisplay: false,
      // サイズ
      size: 1,
      resizable: true,
      // デザイン・挙動
      animate: false,
      hasShadow: true,
      hideOnBlur: false,
      // 起動処理
      startAlone: true,
      startup: true,
      // 表示
      tray: false,
      hideDock: false,
      unique: true
    },
    opacity: 0.9,
    hyperTabs: {
      trafficButtons: false,  // 左上のボタン
      tabIconsColored: true,  // 色付きのアイコン
      border: false           // タブの枠
    },
    hyperBorder: {
      borderColors: ['#728DBC', '#78AAB5']
    },
    hyperline: {
      plugins: ["ip", "memory", "cpu", "network", "spotify"]
    },
    // see http://bit.ly/36gHABI
    pokemon: 'Snorlax',
    poketab: 'true'
  },

  // a list of plugins to fetch and install from npm
  // format: [@org/]project[#version]
  // examples:
  //   `hyperpower`
  //   `@company/project`
  //   `project#1.0.1`
  plugins: [
    // ホットキー
    'hyperterm-overlay',
    // デザイン
    'hyper-opacity',        // 透過
    'hyper-tabs-enhanced',  // タブアイコン
    'hyperborder',          // グラデーションの枠線
    'hyperline',						// ステータスバー
    // 機能
    'hyper-confirm',        // ⌘+q で確認
    'hypercwd',             // 同じディレクトリでタブ or ペイン
    'hyperlinks',           // リンクを開く
    'hyper-search',         // ウィンドウ内検索
    'hyper-pane',           // ペイン操作
    // テーマ
    'hyper-iceberg',     // iceberg テーマ
    // 'hyper-pokemon',        // ポケモンテーマ
    // ジョークプラグイン
    // 'hyperpower',           // アニメーション
    // 'gitrocket',            // git push でロケット
  ],

  // in development, you can create a directory under
  // `~/.hyper_plugins/local/` and include it here
  // to load it and avoid it being `npm install`ed
  localPlugins: [],

  // see http://bit.ly/38t4mbn
  keymaps: {
    // Example
    // 'window:devtools': 'cmd+alt+o',
    "window:reload": "command+r",
    "window:reloadFull": "command+shift+r",
  },
};
