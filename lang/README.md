# Lingua: the 24/7 Latin, Greek and Hebrew channel (v0)

One short verse per lesson, rotating Latin -> Greek -> Hebrew: the verse, a transliteration, a word-by-word gloss
with lemma and parsing, the English (World English Bible), read slowly, word by word, then at normal speed.
Deterministic from open data; no LLM. Sources and licences: [LICENSES.md](LICENSES.md).

    lang/pool/{la,grc,he}.json   committed lesson pool (build_pool.py rebuilds it from deploy/box/lang/fetch_data.sh)
    lang/lesson.py               lesson(n) -> script (steps: card + what is said)
    lang/render.py               cards (HTML/CSS, headless Chromium) + Piper voices + ffmpeg -> clip.mp4
    lang/producer_loop.py        keeps ROOT/inbox N scripts deep (state: ROOT/producer/next_n)
    lang/channel_worker.py       inbox -> clips -> 6 s HLS block -> newsbot.publish under lang/ in ai247-media
    lang/cloudflare/lang-live    Worker config: worker/src with PREFIX=lang/ (deploy-lang.yml)
    site/lang/                   player page, ai-247.pages.dev/lang/
    deploy/box/lang/             systemd user-unit templates; install with deploy/box/install.sh lang [ROOT]

Try it locally (needs ffmpeg; voices from deploy/box/lang/fetch_voices.sh into $LANG_VOICES):

    pip install -r requirements.txt -r lang/requirements.txt && python -m playwright install chromium
    python -m lang.render 0 --out /tmp/l0                       # one lesson -> /tmp/l0/clip.mp4
    python -m lang.producer_loop --root /tmp/lang --target 3 --once
    python -m lang.channel_worker --root /tmp/lang --dry-run --max-blocks 3

Until the box runs it, `.github/workflows/lang-channel.yml` renders and publishes a batch every 4 h.
