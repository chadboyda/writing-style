# zipf_en.bin.gz

A lowercase word and its Zipf value, one per line. Zipf is log10 of the word's frequency per billion words (van Heuven et al., 2014). The file has 147,216 words, each seen at least 5 times. Counts from each source are normalised and weighted equally.

The table is released under CC BY 4.0, with the attribution below. It holds counts only; no text from the sources is included.

| source | licence | tokens counted |
|---|---|---|
| Common Pile `news_filtered` (only articles marked CC BY; CC BY-SA articles skipped) | CC BY 4.0 | 32.3M |
| English Wikinews, 2023-07-28 snapshot | CC BY 2.5 | 6.6M |
| Common Pile `foodista_filtered` | CC BY 3.0 | 11.9M |
| Common Pile `project_gutenberg_filtered` (public-domain books, sample) | Public domain | 10.1M |
| Common Pile `youtube_filtered`, first shard (only CC BY transcripts) | CC BY 4.0 | 40.0M |

Attribution: "Word counts derived from the Common Pile (EleutherAI et al., 2025): news_filtered, foodista_filtered, project_gutenberg_filtered and youtube_filtered; and from English Wikinews (Wikimedia Foundation, CC BY 2.5)."

Paragraphs that also appear in proseweave's open validation corpus were left out of the counts.

Build script: `tools/build_zipf_table.py count`, then `pack`. It is build-time only and needs network access.
