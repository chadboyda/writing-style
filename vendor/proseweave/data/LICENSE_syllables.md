# syllables_en.bin.gz, stress_en.bin.gz and hyph_en_US.dic.gz: sources and licences

All three files may be redistributed, including commercially. None carries a
non-commercial or no-derivatives term. The conditions are these:
- keep the copyright notices and the licence texts below;
- CMUdict: reproduce the notice with binary redistributions;
- hyphen.tex: a modified pattern file must not be named `hyphen.tex`.
  proseweave ships `hyph_en_US.dic` itself, gzipped and otherwise unchanged,
  which is a different file name.

## syllables_en.bin.gz and stress_en.bin.gz: derived from the CMU Pronouncing Dictionary 0.7a

- **Source file:** `cmudict` (cmudict.0.7a), as distributed in the NLTK data
  package `corpora/cmudict`.
- **What proseweave stores:** for each word, the number of vowel phonemes (the
  phones that carry a stress digit) in its first listed pronunciation, with
  words grouped by that count (syllables_en.bin.gz); and, for words of two or
  more syllables not stressed on the first, which syllables of that first
  pronunciation carry primary stress, as a bit mask (stress_en.bin.gz).
  `tools/build_syllables.py` builds both.
- **Licence:** BSD 2-clause, Copyright (C) 1993-2008 Carnegie Mellon University.

The upstream README follows, verbatim:

```
The Carnegie Mellon Pronouncing Dictionary [cmudict.0.7a]

ftp://ftp.cs.cmu.edu/project/speech/dict/
https://cmusphinx.svn.sourceforge.net/svnroot/cmusphinx/trunk/cmudict/cmudict.0.7a

Copyright (C) 1993-2008 Carnegie Mellon University. All rights reserved.

File Format: Each line consists of an uppercased word,
a counter (for alternative pronunciations), and a transcription.
Vowels are marked for stress (1=primary, 2=secondary, 0=no stress).
E.g.: NATURAL 1 N AE1 CH ER0 AH0 L

The dictionary contains 127069 entries.  Of these, 119400 words are assigned
a unique pronunciation, 6830 words have two pronunciations, and 839 words have
three or more pronunciations.  Many of these are fast-speech variants.

Phonemes: There are 39 phonemes, as shown below:
    
    Phoneme Example Translation    Phoneme Example Translation
    ------- ------- -----------    ------- ------- -----------
    AA      odd     AA D           AE      at      AE T
    AH      hut     HH AH T        AO      ought   AO T
    AW      cow     K AW           AY      hide    HH AY D
    B       be      B IY           CH      cheese  CH IY Z
    D       dee     D IY           DH      thee    DH IY
    EH      Ed      EH D           ER      hurt    HH ER T
    EY      ate     EY T           F       fee     F IY
    G       green   G R IY N       HH      he      HH IY
    IH      it      IH T           IY      eat     IY T
    JH      gee     JH IY          K       key     K IY
    L       lee     L IY           M       me      M IY
    N       knee    N IY           NG      ping    P IH NG
    OW      oat     OW T           OY      toy     T OY
    P       pee     P IY           R       read    R IY D
    S       sea     S IY           SH      she     SH IY
    T       tea     T IY           TH      theta   TH EY T AH
    UH      hood    HH UH D        UW      two     T UW
    V       vee     V IY           W       we      W IY
    Y       yield   Y IY L D       Z       zee     Z IY
    ZH      seizure S IY ZH ER

(For NLTK, entries have been sorted so that, e.g. FIRE 1 and FIRE 2
are contiguous, and not separated by FIRE'S 1.)

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
   The contents of this file are deemed to be source code.

2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in
   the documentation and/or other materials provided with the
   distribution.

This work was supported in part by funding from the Defense Advanced
Research Projects Agency, the Office of Naval Research and the National
Science Foundation of the United States of America, and by member
companies of the Carnegie Mellon Sphinx Speech Consortium. We acknowledge
the contributions of many volunteers to the expansion and improvement of
this dictionary.

THIS SOFTWARE IS PROVIDED BY CARNEGIE MELLON UNIVERSITY ``AS IS'' AND
ANY EXPRESSED OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL CARNEGIE MELLON UNIVERSITY
NOR ITS EMPLOYEES BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## hyph_en_US.dic.gz: US English hyphenation patterns

- **Source file:** `hyph_en_US.dic`, version 2011-10-07 (the OpenOffice.org /
  LibreOffice / Hyphen-library conversion by László Németh). It is based on the
  Plain TeX `hyphen.tex` patterns and on the TUGboat US English
  hyphenation-exception log.
- **Copy taken from:** the `dictionaries/` directory of pyphen 0.18.1.
- **How it ships:** gzipped, with the content unchanged.
- **How proseweave uses it:** `readability.py`, which is proseweave's own
  implementation of Liang's (1983) algorithm, uses the patterns only to count
  the syllables of words the dictionary lacks.

The upstream README_hyph_en_US.txt follows, verbatim:

```
hyph_en_US.dic - American English hyphenation patterns for OpenOffice.org

version 2011-10-07

- remove unnecessary parts for the new Hyphen 2.8.2

version 2010-03-16

Changes

- forbid hyphenation at 1-character distances from dashes (eg. ad=d-on)
  and at the dashes (fix for OpenOffice.org 3.2)
- set correct LEFTHYPHENMIN = 2, RIGHTHYPHENMIN = 3
- handle apostrophes (forbid *o'=clock etc.)
- set COMPOUNDLEFTHYPHENMIN, COMPOUNDRIGHTHYPHENMIN values
- UTF-8 encoding
- Unicode ligature support

License

BSD-style. Unlimited copying, redistribution and modification of this file
is permitted with this copyright and license information.

See original license in this file.

Conversion and modifications by László Németh (nemeth at OOo).

Based on the plain TeX hyphenation table
(http://tug.ctan.org/text-archive/macros/plain/base/hyphen.tex) and
the TugBoat hyphenation exceptions log in
http://www.ctan.org/tex-archive/info/digests/tugboat/tb0hyf.tex, processed
by the hyphenex.sh script (see in the same directory).

Originally developed and distributed with the Hyphen hyphenation library,
see http://hunspell.sourceforge.net/ for the source files and the conversion
scripts.

Licenses

hyphen.tex:
% The Plain TeX hyphenation tables [NOT TO BE CHANGED IN ANY WAY!]
% Unlimited copying and redistribution of this file are permitted as long
% as this file is not modified. Modifications are permitted, but only if
% the resulting file is not named hyphen.tex.

output of hyphenex.sh:
% Hyphenation exceptions for US English, based on hyphenation exception
% log articles in TUGboat.
%
% Copyright 2007 TeX Users Group.
% You may freely use, modify and/or distribute this file.
%
% This is an automatically generated file.  Do not edit!
%
% Please contact the TUGboat editorial staff <tugboat@tug.org>
% for corrections and omissions.

hyph_en_US.txt:
See the previous licenses.
```
