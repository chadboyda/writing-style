# Semantic-similarity data: sources and licences

`proseweave/similarity.py` reads the files below. They were built offline, once, with
build-time tools (numpy, scipy, sentence-transformers) that are not part of proseweave. Each
file holds only numbers and word lists; no corpus text is stored.
Each licence has its own file, so share-alike terms apply only to the file whose inputs carry them.

| file | spaces | built from | licence of the file |
|---|---|---|---|
| `similarity_glove.bin.gz` | `glove` | GloVe 6B 100d word vectors (Pennington, Socher & Manning 2014), https://nlp.stanford.edu/projects/glove/ : the 40,000 most frequent words, 4-bit | ODC Public Domain Dedication and License (PDDL) 1.0, as released by Stanford NLP |
| `similarity_wiki.bin.gz` | `wlsa`, `wvec` | an LSA space (log-entropy weighting, truncated SVD) and a word2vec (CBOW) space, trained on WikiText-103 (Merity et al. 2016): 40,000 lemmas x 100 dimensions each, 4-bit | **CC BY-SA 3.0**: an adaptation of WikiText-103, whose text is by the Wikipedia contributors |
| `similarity_sent.bin.gz` | `sent` | a static vector for each of the 30,522 WordPiece tokens of sentence-transformers/all-MiniLM-L6-v2 (revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41), plus that model's token vocabulary. The vectors are trained so that the cosine between two sentences' summed vectors matches the model's cosine. Training used 16.6M public-domain sentences: 1,654 Project Gutenberg books, and the US Congressional Record and congressional hearings (US federal government works, obtained through the Common Pile USGPO collection). 384 dimensions, 4-bit | Apache License 2.0 (the model's licence). The training text is in the public domain in the US. Project Gutenberg's headers and licence text were removed |
| `similarity_routes.json` | - | proseweave's own fitted blend weights and calibration constants | proseweave's licence |

The stop-word list is spaCy's English list (MIT), `data/stop_words_en.txt`; see NOTICE.

## Attribution

- GloVe: Jeffrey Pennington, Richard Socher, Christopher D. Manning. 2014. GloVe: Global
  Vectors for Word Representation. EMNLP. Released under the ODC PDDL.
- WikiText-103: Stephen Merity, Caiming Xiong, James Bradbury, Richard Socher. 2016. Pointer
  Sentinel Mixture Models. Text by the Wikipedia contributors, CC BY-SA 3.0
  (https://creativecommons.org/licenses/by-sa/3.0/). `similarity_wiki.bin.gz` is an
  adaptation and is shared under the same licence. The licence covers that file only.
- all-MiniLM-L6-v2: Nils Reimers, Iryna Gurevych and the sentence-transformers contributors,
  Apache License 2.0. Only fitted word vectors are stored, not the model.
- Project Gutenberg texts: public domain in the United States.
- US Congressional Record and hearing transcripts: works of the US federal government (17 U.S.C. 105), public domain; obtained through the Common Pile v0.1 `usgpo_filtered` collection (Kandpal et al. 2025).

The method follows the published cohesion research: summed word vectors compared by cosine,
adjacent-segment windows, and sentence similarity from sentence embeddings. See Landauer &
Dumais (1997), Crossley, Kyle & McNamara (2016), and Reimers & Gurevych (2019).
