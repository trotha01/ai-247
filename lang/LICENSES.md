# Language channel: sources and licences

Every source was checked first-hand in its own repository or page on 2026-11-07. All of them allow commercial use.
Non-commercial sources are excluded (listed at the end).

| What | Source | Licence (where it is stated) | Used for |
|---|---|---|---|
| Greek text | SBLGNT, Logos Bible Software, via MACULA Greek | CC BY 4.0 (github.com/LogosBible/SBLGNT README and repo licence, relicensed 2022-12-19) | verse text |
| Greek lemmas, morphology, English glosses | MACULA Greek, Biblica (github.com/Clear-Bible/macula-greek) | CC BY 4.0 (LICENSE.md); `english` glosses: Cherith Glosses, CC BY 4.0; `gloss`: Berean Interlinear, public domain since 2023-04-30 | lemma, parsing, gloss |
| Hebrew text | Westminster Leningrad Codex | public domain (OSHB LICENSE.md; tanach.us: "may be viewed or copied without restriction") | verse text |
| Hebrew morphology | Open Scriptures Hebrew Bible (github.com/openscriptures/morphhb) | CC BY 4.0 (LICENSE.md; attribution: "Original work of the Open Scriptures Hebrew Bible available at https://github.com/openscriptures/morphhb") | lemma, parsing |
| Hebrew transliteration, glosses | MACULA Hebrew, Biblica (github.com/Clear-Bible/macula-hebrew) | CC BY 4.0 (LICENSE.md); glosses: Cherith, CC BY 4.0 | transliteration, gloss |
| Latin text | Clementine Vulgate, VulSearch text by M. Tweedale (sourceforge.net/projects/vulsearch, clemtext/source/Quasimodo.zip) | the 1592 text is public domain by age; the zip carries no licence file and the SourceForge project is tagged GPLv2, which also allows commercial use. Flag: no explicit statement for the transcription itself was found first-hand | verse text |
| Latin dictionary and inflections | William Whitaker's WORDS (github.com/mk270/whitakers-words) | LICENCE.txt: "Permission is hereby freely given for any and all use of program and data." | lemma, parsing, gloss (lang/latin.py) |
| English | World English Bible (ebible.org, engwebp) | public domain (engwebp_about.htm); a changed text may not be called "World English Bible" (we do not change it) | translation |
| Voice: Latin | Piper it_IT-paola-medium (rhasspy/piper-voices) | model card: dataset huggingface.co/datasets/paolapersico1/Voice-Dataset-Italian, licence cc0-1.0 (dataset card) | Latin, read from an ecclesiastical respelling |
| Voice: Greek, Hebrew | Piper el_GR-rapunzelina-medium | model card: dataset licence CC0 | Greek; Hebrew via IPA phonemes |
| Voice: English | Piper en_US-ljspeech-medium | model card: LJ Speech dataset, public domain | narration, glosses, translation |
| Fonts | Noto Serif, Noto Serif Hebrew (github.com/google/fonts) | SIL Open Font License 1.1 (lang/fonts/OFL.txt) | cards |

Attribution is on every card (footer) and on the player page (site/lang/index.html).

## Excluded (non-commercial or unclear)
- Piper el_GR-joy: dataset CC BY-NC 4.0.
- Piper he_IL-saspeech: SASPEECH (openslr.org/134) is "Custom non-commercial". Hebrew is therefore spoken by the
  Greek voice from IPA built from the transliteration (lang/translit.py `hebrew_ipa`).
- Piper it_IT-riccardo: M-AILABS dataset page did not resolve, so the licence could not be checked; not used.
- MorphGNT's own parsing (CC BY-SA 3.0): not needed, MACULA has the same data under CC BY.
- BHSA, PROIEL (Latin Vulgate morphology), MMS-TTS, XTTS: non-commercial (reports/channel-pipeline-survey.org).
- MACULA fields "used with permission" (MARBLE/SDBH semantic domains): not used.
