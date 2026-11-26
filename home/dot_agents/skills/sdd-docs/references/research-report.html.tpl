<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{{TITLE}}</title>
<style>
body { max-width: 72rem; margin: 2rem auto; padding: 0 1rem; font: 1rem/1.65 system-ui, sans-serif; }
figure { margin: 1rem 0; }
img { max-width: 100%; height: auto; }
td, th { text-align: left; padding: .3rem .6rem; border-bottom: 1px solid; }
pre { overflow: auto; padding: .6rem; border: 1px solid; }
</style>
</head>
<body>
<main>
<h1>{{TITLE}}</h1>
<p>観測日: <time datetime="{{DATE}}">{{DATE}}</time></p>
<section id="summary"><h2>結論</h2><p>{{SUMMARY}}</p></section>
<section id="question"><h2>問い</h2><p>{{QUESTION}}</p></section>
<section id="conditions"><h2>対象の版・条件</h2><p>{{CONDITIONS}}</p></section>
<section id="results">
<h2>結果</h2>
<p>{{RESULTS}}</p>
<figure><img src="{{IMAGE_DATA_URI}}" alt="{{IMAGE_ALT}}"><figcaption>{{CAPTION}}</figcaption></figure>
</section>
<section id="reproduce"><h2>再現コマンド・入力・出典</h2><pre><code>{{COMMAND}}</code></pre><p>{{SOURCES}}</p></section>
<section id="limitations"><h2>限界・未確認</h2><p>{{LIMITATIONS}}</p></section>
</main>
</body>
</html>
