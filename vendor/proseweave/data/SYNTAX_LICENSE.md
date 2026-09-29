# syntax_en.bin.gz: provenance and licence

`syntax_en.bin.gz` holds the learned weights of proseweave's text pipeline
(`proseweave/syntax.py`):
- a two-pass part-of-speech tagger
- a sentence segmenter
- a dependency parser
- a coarse-class model

It also holds a tag dictionary, a short list of lemma corrections and a
short list of tokenizer exceptions.

It contains feature weights only. Nothing from any training source is stored
in it beyond single words and word pairs used as feature names, and the short
lists.

## How it was made

The weights come from greedy averaged-perceptron training, following the
published literature on transition parsing (Kuhlmann et al. 2011; Goldberg &
Nivre 2012, 2013). The scripts are in `tools/syntax/`: `train.py` and
`train_seg2.py`, with `repack.py` and `pack_binary.py` for the shipped file.

The training labels are automatic annotations of open texts, made at build
time by spaCy's `en_core_web_sm` 3.7 model. That model is under the MIT
licence, Copyright (C) 2016-2024 ExplosionAI GmbH.

| Source | Licence | Used for |
|---|---|---|
| Universal Dependencies English Web Treebank (UD_English-EWT), train split, raw sentences | CC BY-SA 4.0 (Silveira et al. 2014; Universal Dependencies contributors) | all models |
| English Wikipedia, randomly sampled articles, plain-text extracts (2026-09) | CC BY-SA 4.0 (Wikipedia contributors) | all models |
| English Wikinews, randomly sampled articles (2026-09) | CC BY 2.5 (Wikinews contributors) | all models |
| Project Gutenberg books (list in `tools/syntax/fetch_text.py`) | public domain in the United States | all models |
| Common Pile v0.1 `news_filtered`, articles marked CC BY 4.0 only (CC BY-SA ones skipped), plus Foodista (CC BY 3.0) and English Wikinews (CC BY 2.5), about 3M words (`tools/dump_news.py`) | as listed | sentence segmenter |

No Gutenberg header, licence text or trademark is used or reproduced.

The UD EWT dev and test splits were used only to measure the finished models.
No text from the article corpus (texts not redistributed) was used for
training. It was used only to measure the finished pipeline.

Some training text is CC BY-SA 4.0, so the file is distributed under
**CC BY-SA 4.0**. Attribution goes to the Universal Dependencies EWT
contributors, the Wikipedia and Wikinews contributors, and the Common Pile,
Foodista and news authors named in their sources. The spaCy model's MIT notice
is reproduced below.

## MIT notice (spaCy en_core_web_sm)

The MIT License (MIT). Copyright (C) 2016-2024 ExplosionAI GmbH, 2016 spaCy
GmbH, 2015 Matthew Honnibal. Permission is hereby granted, free of charge, to
any person obtaining a copy of this software and associated documentation files
(the "Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, and to permit persons to whom
the Software is furnished to do so, subject to the following conditions: The
above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS
IS", WITHOUT WARRANTY OF ANY KIND.
