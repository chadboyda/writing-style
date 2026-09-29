"""Judgement-scale properties, from reader-level Jev questions plus proseweave indices.

narrativity, word_concreteness, syntactic_simplicity, referential_cohesion,
deep_cohesion and overall_quality are on the scale of the LLM easability judge
used for validation (see validation/): each is a ridge combination of
the whole-text Jev Score answers below (expected level over the returned
probabilities, several paraphrases per construct), six reader-level factors
built from them, a genre Choice (its probabilities), and indices proseweave
computes locally; each property is the mean of four ridge models over nested
feature pools. Weights were fitted
on the even-indexed halves of both validation corpora (data/judged_models.json).

referential_cohesion_construct and deep_cohesion_construct follow the
definitions of Graesser, McNamara & Kulikowich (2011): adjacent-sentence
overlap of nouns, arguments and content words; and causal and logical
connectives. Each is the mean z-score of those proseweave indices, shown as
50 + 10 z.

    ans = j.ask_many(jobs(text))            # the whole text, then ~300-word chunks
    compose(ans[0], local, text, ans[1:])   # local: see local_inputs()
"""
from __future__ import annotations

import json
import pathlib
import re
import statistics

from . import jev as jevmod

DATA = pathlib.Path(__file__).resolve().parent / "data" / "judged_models.json"
_MODEL = None

# Score questions: (instructions, levels from low to high; levels describe situations).
QUESTIONS = {'A_ref_pron': ('How easy is it to tell who or what each pronoun (he, she, it, they, this) refers to?',
                ['Often unclear', 'Sometimes unclear', 'Almost always clear', 'Always obvious']),
 'C_abstract': ('How much of the vocabulary is abstract nouns like policy, theory, process, value, system?',
                ['Hardly any', 'A little', 'A fair amount', 'A lot', 'Almost all of it']),
 'C_everyday': ('How everyday are the words - words a child would know - as opposed to specialist or '
                'academic words?',
                ['Mostly specialist or academic words',
                 'Many specialist words',
                 'A mix',
                 'Mostly everyday words',
                 'Almost entirely everyday words']),
 'C_mirror': ('Word concreteness: concrete vs abstract vocabulary. How concrete is the vocabulary?',
              ['Almost all abstract: ideas, qualities, processes, theories',
               'Mostly abstract, with a few physical things named',
               'An even mix of abstract ideas and physical things',
               'Mostly things you can see, touch, hear or picture',
               'Almost all physical: objects, bodies, places, actions you can picture']),
 'C_picture': ('How easy is it to picture what the text describes?',
               ['Nothing to picture: all concepts and argument',
                'A few images',
                'About half the text can be pictured',
                'Most of it can be pictured',
                'Nearly every sentence calls up a picture']),
 'C_senses': ('How much sensory detail - sight, sound, smell, touch, taste - does the text give?',
              ['None', 'A touch', 'Some', 'Plenty', 'It is full of sensory detail']),
 'C_things': ('How often does the text name physical objects, places, bodies, food, animals or weather?',
              ['Almost never', 'Occasionally', 'Regularly', 'Very often', 'In nearly every sentence']),
 'D_connect': ('How well does the writer spell out the connections between ideas - because, so, but, '
               'therefore, as a result?',
               ['Connections are never spelled out',
                'Rarely',
                'Sometimes',
                'Often',
                'Every connection is spelled out']),
 'D_goal': ('How clear are the goals, motives or purposes behind what people do or what is proposed?',
            ['Never stated', 'Rarely stated', 'Sometimes', 'Usually', 'Always clear']),
 'D_logic': ('How clearly do the ideas build on one another in a logical order?',
             ['No order: a heap of points',
              'Loose order',
              'Reasonably ordered',
              'Clearly built up',
              'Each idea follows necessarily from the last']),
 'D_why': ('How well does the text explain why things happen, not just what happens?',
           ['Not at all', 'Barely', 'Somewhat', 'Well', 'Thoroughly: causes and reasons throughout']),
 'G_corporate': ('How much does the text read like corporate marketing, a press release, or content written '
                 'to rank in search results?',
                 ['Not at all: an individual writer with something to say',
                  'A little promotional in places',
                  'Largely promotional or formulaic',
                  'Entirely marketing, press-release or SEO copy']),
 'G_craft': ('How carefully crafted is the prose - sentence rhythm, imagery, word choice?',
             ['Careless or mechanical', 'Plain and functional', 'Well crafted', 'Masterfully crafted']),
 'G_debris': ('How much of the text is web-page clutter rather than prose: menus, buttons, captions, code, '
              'repeated headings, link lists, sign-up prompts?',
              ['None or almost none', 'A few stray lines', 'A noticeable share', 'A large share']),
 'G_scene': ('How much of the text is set in particular scenes - specific people, places and moments?',
             ['None: general claims and abstractions',
              'A few particular moments',
              'Much of it',
              'Almost all of it']),
 'H_engage': ('How engaging is the text to read?',
              ['Dull or off-putting', 'Occasionally interesting', 'Engaging', 'Gripping']),
 'H_plain': ('How plain and conversational is the language, as opposed to formal, abstract or jargon-heavy?',
             ['Formal, abstract or full of jargon',
              'Somewhat formal',
              'Mostly plain',
              'Plain, everyday, conversational']),
 'H_story': ('Is the text told through people doing things over time?',
             ['No: ideas, facts or claims only', 'A little', 'Largely', 'Entirely']),
 'M_qual': ('Overall writing quality.',
            ['Poor writing: hard to read, error-prone or empty',
             'Weak writing with some merit',
             'Competent, workmanlike writing',
             'Good writing: clear, engaging and well made',
             'Excellent, memorable writing']),
 'N_events': ('How much of the text reports particular events - someone did something at some time?',
              ['None: general statements only',
               'One or two events mentioned in passing',
               'Several events, but the text is organised around ideas',
               'Events make up most of the text',
               'Nearly every sentence reports an event']),
 'N_genre': ('Which best describes the text?',
             ['A reference, technical or instructional document',
              'An argument, analysis or report of facts',
              'An essay mixing reflection and anecdote',
              'A narrative account, memoir or profile',
              'Fiction or a told story']),
 'N_mirror': ('Narrativity: story-like qualities - agents, events, temporal markers. How story-like is this '
              'text?',
              ['An exposition of ideas, facts or instructions with no events or characters',
               'Mostly exposition, with a brief anecdote or example of someone doing something',
               'A mix: explanation interleaved with events that happen to people',
               'Mostly an account of people doing things over time, with some explanation',
               'A story throughout: characters acting, events in sequence, time moving on']),
 'N_people': ('How much is the text about particular people (or animals) and what they do, feel and say?',
              ['No particular people at all',
               'People are mentioned but do little',
               'Some passages follow particular people',
               'Mostly follows particular people',
               'Entirely about particular people and their actions']),
 'N_time': ('How much does the text move forward in time - then, later, next morning, after that?',
            ['Not at all: it is organised by topic or argument',
             'Occasional time references',
             'Some stretches follow a sequence in time',
             'Mostly a sequence in time',
             'A continuous sequence from start to end']),
 'N_voice': ('How conversational and everyday is the language, as in speech or storytelling?',
             ['Formal, technical or academic throughout',
              'Mostly formal',
              'Plain, neither formal nor chatty',
              'Mostly conversational',
              'Chatty, like someone talking']),
 'P_engage': ('Would a general reader want to keep reading this?',
              ['No, they would stop quickly', 'Probably not', 'Probably', 'Yes, eagerly']),
 'P_qual': ('How good is this piece of writing, all things considered?',
            ['Bad', 'Mediocre', 'Decent', 'Good', 'Outstanding']),
 'P_story': ('How much of the text tells what happened to someone - events in order, people acting?',
             ['None', 'A little', 'About half', 'Most of it', 'All of it']),
 'Q_clarity': ('How clear is the writing?',
               ['Confusing', 'Often unclear', 'Mostly clear', 'Clear', 'Crystal clear']),
 'Q_craft2': ('How skilful is the writing at the level of the sentence?',
              ['Clumsy', 'Plain and uneven', 'Competent', 'Skilful', 'Masterly']),
 'Q_overall': ('Taking everything into account, how good is this writing?',
               ['Poor', 'Below average', 'Average', 'Good', 'Excellent']),
 'Q_reader': ('How much would a thoughtful general reader get out of reading this?',
              ['Nothing: a waste of time', 'Little', 'Something', 'A good deal', 'A great deal']),
 'R_pron': ("How clear is it what each 'he', 'she', 'it', 'they' or 'this' refers to?",
            ['Often unclear or ambiguous',
             'Sometimes unclear',
             'Mostly clear',
             'Clear almost always',
             'Always obvious']),
 'R_repeat': ('How often do key words from one sentence come back in the next few?',
              ['Rarely', 'Occasionally', 'Regularly', 'Often', 'Constantly']),
 'R_same': ('How much do consecutive sentences talk about the same people, things or ideas?',
            ['Almost never: each sentence moves to something new',
             'Now and then',
             'About half the time',
             'Usually',
             'Nearly always: the same few subjects run through']),
 'R_thread': ('How easy is it to follow the thread of the text from one paragraph to the next?',
              ['Very hard: it jumps around', 'Hard in places', 'Moderately easy', 'Easy', 'Effortless']),
 'X_ease1': ('How smoothly does a general reader move through this text?',
             ['They would stall often: dense, jargon-heavy or disjointed',
              'They would slow down in many places',
              'Steady reading with occasional effort',
              'Smooth reading',
              'Effortless, it carries the reader along']),
 'X_ease2': ('How clearly does each sentence connect to the one before?',
             ['Sentences often seem unrelated',
              'Connections are frequently unclear',
              'Usually clear',
              'Almost always clear',
              'Every sentence follows naturally']),
 'X_ease3': ('How clearly are reasons and consequences explained?',
             ['Claims are made without reasons',
              'Reasons appear occasionally',
              'Reasons are given for the main points',
              'Most points come with their why',
              'A clear chain of reasons throughout']),
 'X_human': ('Does the text read like a person with something to say, rather than filler or marketing?',
             ['Pure filler or marketing copy',
              'Mostly generic copy',
              'Mixed',
              'Mostly a real voice with something to say',
              'Unmistakably a person with something to say']),
 'X_polish1': ('How polished is the prose - every sentence finished, clean and deliberate?',
               ['Rough: errors, fragments and clumsy phrasing',
                'Serviceable with rough patches',
                'Clean and competent',
                'Polished throughout',
                'Immaculate, professional-grade prose']),
 'X_polish2': ('How much would a good editor need to change?',
               ['A full rewrite', 'Heavy edits throughout', 'Some line edits', 'A light touch', 'Nothing']),
 'X_track': ('How easy is it to keep track of who and what the text is talking about?',
             ['Hard: new names and things keep appearing',
              'Often hard',
              'Usually easy',
              'Easy throughout',
              'Trivially easy: a few familiar subjects throughout']),
 'ease_2': ('Could a curious 14-year-old follow this text?',
            ['No, it would lose them quickly', 'Only parts of it', 'Most of it', 'All of it, easily']),
 'ease_3': ('How familiar is the vocabulary to an everyday reader?',
            ['Full of specialist, technical or abstract terms',
             'Some specialist terms',
             'Mostly everyday words',
             'Everyday words throughout']),
 'engage_1': ('How much would an ordinary reader enjoy reading this?',
              ['Not at all', 'A little', 'Quite a lot', 'Very much']),
 'engage_2': ("How well does the text hold the reader's attention from start to finish?",
              ['It loses the reader almost at once',
               'It holds attention in patches',
               'It holds attention most of the way',
               'It holds attention throughout']),
 'engage_3': ('How vivid and alive does the writing feel?',
              ['Flat and lifeless', 'Occasionally vivid', 'Mostly vivid', 'Vivid throughout']),
 'junk_1': ('How much of the text is boilerplate, navigation, promotional copy or filler?',
            ['None', 'A little', 'A good deal', 'Most of it']),
 'junk_2': ('Does the text read as if generated to fill a page or sell something, rather than written by '
            'someone with something to say?',
            ['No, clearly someone with something to say',
             'Mostly written with purpose',
             'Partly filler or sales copy',
             'Mostly filler or sales copy']),
 'qual_1': ('How well written is this text?', ['Poorly', 'Passably', 'Well', 'Superbly']),
 'qual_3': ('How much care and skill went into the writing?',
            ['Very little', 'Some', 'A good deal', 'A great deal']),
 'story_1': ('How much of the text follows particular people through things that happen to them?',
             ['None', 'A little', 'Much of it', 'Nearly all of it']),
 'story_2': ('Is the text organised as a sequence of events in time?',
             ['No: organised by topic, claim or list', 'Partly', 'Mostly', 'Entirely']),
 'story_3': ('How much dialogue, action or scene is there, as opposed to explanation and summary?',
             ['None: all explanation or summary', 'A little', 'A fair amount', 'Mostly scene and action'])}


def model() -> dict:
    global _MODEL
    if _MODEL is None:
        _MODEL = json.loads(DATA.read_text())
    return _MODEL


def jev_questions() -> dict:
    qs = {k: {"type": "score", "instructions": q, "criteria": lv} for k, (q, lv) in QUESTIONS.items()}
    qs["GENRE"] = {"type": "choice", "instructions": "What kind of writing is this?", "criteria": model()["genres"]}
    return qs


def chunks(text: str, size: int = 300) -> list[str]:
    """Paragraph-aligned pieces of about `size` words; a short tail joins the last piece."""
    paras = [p for p in text.split("\n") if p.strip()]
    out, cur = [], []
    for p in paras:
        cur.append(p)
        if sum(len(x.split()) for x in cur) >= size:
            out.append("\n".join(cur)); cur = []
    if cur:
        if out and sum(len(x.split()) for x in cur) < size / 2:
            out[-1] += "\n" + "\n".join(cur)
        else:
            out.append("\n".join(cur))
    return out


def jobs(text: str) -> list[tuple]:
    """Every Jev request compose() needs: the whole text, then each chunk (Score bank only)."""
    bank = {k: v for k, v in jev_questions().items() if k != "GENRE"}
    return [(text, jev_questions())] + [(c, bank) for c in chunks(text)]


def fragment_lines(text: str) -> float:
    """Share of non-empty lines under 8 words or not ending like a sentence."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    frag = sum(1 for l in lines if len(l.split()) < 8 or not re.search(r"[.!?\"'\u201d\u2019)]$", l))
    return frag / max(len(lines), 1)


def local_inputs() -> list[str]:
    """Names of the proseweave indices compose() needs in `local`."""
    m = model()
    need = {c for ms in m["ensemble"].values() for pm in ms for c in pm["terms"]} |         {c for v in m["factors"].values() for c in v}
    return sorted(need - set(QUESTIONS) - set(m["factors"]) - {"HALO", "L_fragment_lines"}
                  - {"GEN_" + g for g in m["genres"]} - {"K_" + q for q in QUESTIONS})


def compose(answers: dict, local: dict, text: str | None = None, chunk_answers: list | None = None) -> dict:
    """The six judge-scale properties and the two construct properties.
    local: {index name: value} for local_inputs() plus the construct indices;
    text: the document (for the fragment-line share)."""
    m = model()
    x = dict(local)
    if text is not None:
        x["L_fragment_lines"] = fragment_lines(text)
    for k, (_, lv) in QUESTIONS.items():
        v = jevmod.score_value(answers.get(k), len(lv))
        x[k] = None if v is None else v / (len(lv) - 1)
    acc = {}
    for ca in chunk_answers or []:
        for k, (_, lv) in QUESTIONS.items():
            v = jevmod.score_value(ca.get(k), len(lv))
            if v is not None:
                acc.setdefault(k, []).append(v / (len(lv) - 1))
    for k, vs in acc.items():
        x["K_" + k] = statistics.fmean(vs)
    probs = (answers.get("GENRE") or {}).get("probabilities") or {}
    for g in m["genres"]:
        x["GEN_" + g] = float(probs.get(g, 0.0))
    z = m["item_z"]
    for name, keys in m["factors"].items():
        vals = [(x[k] - z[k][0]) / (z[k][1] or 1.0) for k in keys if x.get(k) is not None]
        x[name] = m["factor_sign"].get(name, 1) * statistics.fmean(vals) if vals else 0.0
    x["HALO"] = statistics.fmean(x[n] for n in m["factors"])
    out = {}
    for p, members in m["ensemble"].items():      # mean of the pooled ridge models
        vals = []
        for pm in members:
            if all(x.get(c) is not None for c in pm["terms"]):
                vals.append(pm["intercept"] + sum(w * (x[c] - mu) / (sd or 1.0)
                                                  for c, (w, mu, sd) in pm["terms"].items()))
        out[p] = max(0.0, min(100.0, statistics.fmean(vals))) if vals else None
    cz = m["construct"]["z"]
    for name, keys in m["construct"]["indices"].items():
        if all(local.get(k) is not None for k in keys):
            zs = statistics.fmean((local[k] - cz[k][0]) / (cz[k][1] or 1.0) for k in keys)
            out[name] = 50 + 10 * zs
        else:
            out[name] = None
    return out
