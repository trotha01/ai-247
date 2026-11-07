#!/bin/bash
# Download the open texts lang/build_pool.py reads (only needed to REBUILD lang/pool/*.json; the channel itself runs
# from the committed pool). Licences: lang/LICENSES.md.  Usage: fetch_data.sh DIR
set -eu
D=${1:?usage: fetch_data.sh DIR}
mkdir -p "$D" && cd "$D"
for r in macula-greek macula-hebrew; do
  [ -d $r ] || { git clone -q --depth 1 --filter=blob:none --sparse https://github.com/Clear-Bible/$r.git $r
                 (cd $r && git sparse-checkout set --no-cone '/*.md' '/SBLGNT/tsv/*' '/WLC/tsv/*'); }
done
# the Hebrew TSV is a Git LFS object
curl -fsSL -o macula-hebrew/WLC/tsv/macula-hebrew.tsv https://media.githubusercontent.com/media/Clear-Bible/macula-hebrew/main/WLC/tsv/macula-hebrew.tsv
[ -d words ] || git clone -q --depth 1 https://github.com/mk270/whitakers-words.git words
mkdir -p clem && (cd clem && curl -fsSL -o q.zip "https://sourceforge.net/projects/vulsearch/files/clemtext/source/Quasimodo.zip/download" && unzip -qo q.zip)
mkdir -p web && (cd web && curl -fsSL -o v.zip https://ebible.org/Scriptures/engwebp_vpl.zip && unzip -qo v.zip)
echo "data in $D; now: python -m lang.build_pool --data $D"
