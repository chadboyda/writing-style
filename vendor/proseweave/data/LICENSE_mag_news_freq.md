# mag_news_freq.bin.xz: licence and attribution

`mag_news_freq.bin.xz` holds word and phrase counts: lemma unigrams, lemma
n-grams (2 to 4 words) and word-class-masked n-grams. They were counted from
the open-licensed English texts listed below. The file contains no running
text. The longest item it holds is a four-word sequence with its count.
Counted from scratch from the open sources below. Not derived from COCA or
from any other tool's frequency lists.

The build script is `tools/build_mag_news_freq.py`. It downloads the inputs
from Hugging Face, reads every paragraph with proseweave's own pipeline (the
lists its source comparison uses), counts, sums the corpus groups, drops items
below 0.253 occurrences per million, and packs what remains.

The tables are released under **CC BY 4.0**. Please keep the attributions
below when you redistribute them.

## Inputs

| group | source | licence | used |
|---|---|---|---|
| news | Common Pile v0.1, `common-pile/news_filtered`: articles from 360info, Alt News, Balkan Diskurs, EduCeleb, Factly, Freedom of the Press Foundation, Liberty TV Radio, Mekong Eye, Milwaukee Neighborhood News Service, Minority Africa, New Canadian Media, Oxpeckers, Propastop, The Public Record, ZimFact and others | CC BY 4.0, per article (the article's `metadata.license`) | only the articles marked CC BY. Articles marked CC BY-SA are skipped |
| globalvoices | the same dataset, Global Voices articles | CC BY (as marked per article) | only the articles marked CC BY |
| wikinews | English Wikinews, snapshot of 2023-07-28 (`izumi-lab/wikinews-en-20230728`) | CC BY 2.5 (Wikinews content) | article pages only. Namespace pages and the archive/share footers are dropped |
| foodista | Common Pile v0.1, `common-pile/foodista_filtered` | CC BY 3.0 | all |
| gutenberg | Common Pile v0.1, `common-pile/project_gutenberg_filtered`, first shard | public domain (US) | the first 10M words of books marked Public Domain, at most 100k words per book, excluding Bible editions |

Attribution: "Word and phrase counts derived from Global Voices, Wikinews,
Foodista, the news sites collected in Common Pile v0.1 (Kandpal et al., 2025,
*The Common Pile v0.1*), and Project Gutenberg texts, used under CC BY 4.0,
CC BY 3.0, CC BY 2.5 and public domain terms respectively."

## Build-time tools (not bundled)

- Tokens, sentences, Penn tags, word classes and lemmas came from proseweave
  itself: its bundled parser and tagger (`syntax.py`, data/SYNTAX_LICENSE.md),
  its tagger rules (`tagger_classes.py`) and its lemma tables (see NOTICE), run
  without Jev.
- numpy (BSD) and pyarrow (Apache 2.0) were used for counting and reading.

No word list, frequency list or data file from any other text-analysis tool
went into the build.
