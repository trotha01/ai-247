# Channels on this machine

Everything lives in this folder (installed by `deploy/box/install.sh` from trotha01/ai-247). Move it to another box
by running the same script there: no host-specific paths are in the code.

    src/ai-247/      code checkout (updated by install.sh)
    venv/            Python environment          voices/   Piper voices
    tools/           ffmpeg + Chromium (nix out-links when nix is present)
    lang/            language channel: env, r2.env (secret, mode 600), run/ (inbox, work; capped at 3 GB)

The services are systemd *user* units of the installing account (lingering on, so they start at boot).

## Language channel (Lingua)  ->  https://ai-247.pages.dev/lang/

    systemctl --user status lang-producer lang-worker      # state
    journalctl --user -fu lang-worker                       # live log ("ON AIR block ..." per lesson)
    systemctl --user restart lang-worker lang-producer      # restart
    systemctl --user stop lang-worker lang-producer         # stop (the stream keeps looping recent lessons, then the replay pool)
    systemctl --user disable --now lang-worker lang-producer   # stop and keep it off after reboot
    curl -s https://lang-live.trotha01.workers.dev/healthz  # what is on air

From another account (e.g. Mychal, with sudo), prefix the commands to act as the owner, here `trevor`:

    sudo -u trevor XDG_RUNTIME_DIR=/run/user/$(id -u trevor) systemctl --user status lang-worker
    sudo journalctl _SYSTEMD_USER_UNIT=lang-worker.service -f

Update to the latest code: `bash src/ai-247/deploy/box/install.sh lang` (re-runnable).
