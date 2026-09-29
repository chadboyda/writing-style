# AI tells: a detection catalog

Patterns that mark text as machine-written, with the fix for each. The pattern
categories draw on
[Wikipedia: Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing),
which the volunteers of WikiProject AI Cleanup built up from thousands of
flagged edits; the wording and every example here are our own.

Inspired by humanizer (https://github.com/blader/humanizer) by Siqi Chen.

Use this during the final editorial pass, after the draft exists. It is a
detection aid, not a style guide. [writing-best-practices.md](writing-best-practices.md)
governs the prose itself.

## Read this first: the author's baseline arbitrates

Every pattern below is a *tell* only when it is not already how the author
writes. Em dashes, bold labels, and three-part lists are real habits of real
people. Stripping them from someone whose own writing is full of them does not
remove an AI tell. It removes the author, which is the one failure this skill
exists to prevent.

So the order matters:

1. **Profile the retrieved samples first.** `scripts/check_ai_tells.py profile`
   computes the author's own rate for every mechanically detectable pattern.
2. **Scan the draft against that profile.** `scan --baseline <profile.json>`
   reports only what exceeds the author's own rate.
3. **Fix what the scan flags,** plus the judgment-call patterns below that no
   script can see.

With no samples (retrieval failed, or this is a first draft with nothing to
match) fall back to the absolute thresholds. They are tuned to "conspicuous,"
not "zero." One em dash in a paragraph is punctuation; five is a tell.

The catalog is a prompt to look, never a find-and-replace list. A pattern that
survives scrutiny because it is doing real work stays.

Every example below is invented. The towns, venues, firms and people in them do
not exist.

---

## Content inflation

### 1. Manufactured significance

**Watch:** a pivotal/crucial/key moment, turning point, marking a shift, is a
testament to, stands/serves as, deeply rooted, indelible mark, reflects broader,
underscores its importance, evolving landscape

An ordinary fact gets promoted to a symbol of some larger movement, and the
sentence spends its length on the promotion instead of the fact.

> The ferry line opened in 1971, a turning point for the island that reflects
> a broader shift in how coastal communities think about connection.

> The ferry line opened in 1971 and cut the trip to the mainland from a day to
> forty minutes.

### 2. Notability padding

**Watch:** a leading expert, national media outlets, independent coverage,
active social media presence

The draft proves someone matters by stacking up where they have appeared, and
never says what they did there.

> Her work has been featured in major national newspapers, several food
> magazines, and a streaming documentary. She has a large, engaged following
> across social platforms.

> A regional paper's 2023 profile credited her with reviving the bay's oyster
> beds; she paid two divers out of pocket to reseed them.

### 3. Participial depth ("-ing" tails)

**Watch:** highlighting…, underscoring…, ensuring…, reflecting…, showcasing…,
fostering…, contributing to…

The sentence is finished, then a comma and a present participle tack on an
interpretation nobody asked for. It reads as analysis and contains none.

> The library's new glass wall faces the river, inviting light into the reading
> room, reflecting the town's openness to learning and underscoring its role as
> a civic anchor.

> The library's new glass wall faces the river. On clear afternoons the reading
> room needs no overhead lights.

### 4. Brochure voice

**Watch:** nestled, in the heart of, breathtaking, stunning, vibrant, rich
(figurative), renowned, must-visit, boasts a, showcasing, commitment to

Travel-copy adjectives turn up where a plain description was wanted, most often
in writing about a place.

> Nestled amid rolling vineyard country, the Quillmoor Inn boasts breathtaking
> views, a renowned kitchen, and a vibrant commitment to local flavor.

> The Quillmoor Inn has eleven rooms above a working vineyard. Dinner is a single
> set menu, and the lamb comes from the farm across the road.

### 5. Vague attribution

**Watch:** experts argue, observers have cited, some critics, industry reports,
several sources

The claim leans on an authority with no name, no date and no document behind it.

> Experts say the new bus lanes have transformed the city's commute, and many
> observers see them as a model for the region.

> Average rush-hour trips on Route 9 fell from 41 minutes to 29 in the six
> months after the lanes opened, according to the transit agency's ridership
> report.

### 6. Formulaic "challenges and future prospects"

**Watch:** faces several challenges, despite its…, despite these challenges,
headings such as "Future Outlook" or "Challenges and Legacy"

A closing paragraph names a few problems in the abstract, then waves them away
with a line about resilience. Nothing in it could be checked.

> Despite its rapid growth, Wenlow Harbor faces several challenges, including
> rising rents and aging infrastructure. Despite these challenges, the town
> remains a beloved destination with a bright future ahead.

> Rents in Wenlow Harbor rose 30 percent between 2019 and 2023, and the council
> has twice postponed replacing sewer mains laid in the 1950s.

---

## Language and grammar

### 7. AI vocabulary

**Verbs:** delve, underscore, highlight, showcase, enhance, foster, garner,
align with, emphasize
**Adjectives:** pivotal, crucial, key, intricate, enduring, vibrant, valuable
**Nouns:** tapestry, testament, interplay, landscape (abstract)
**Connective:** additionally

None is wrong alone; they cluster. The script counts density, so a cluster is
the signal and a single instance is not.

### 8. Copula avoidance

**Watch:** serves as, stands as, represents, boasts, features, offers

A grander verb stands in for plain *is* or *has*, as if the simple verb were
beneath the subject.

> The old grain depot now serves as the collective's main venue and boasts a
> 200-seat hall.

> The old grain depot is now the collective's main venue. Its hall seats 200.

### 9. Negative parallelism

**Watch:** not just X but Y, not only… but also, it's not merely… it's

> This isn't just a budgeting app; it's a new relationship with your money. It's
> not merely about tracking spending, it's about taking back control.

> The app files each purchase under a category and warns you when one runs over.

A real contrast is fine: *"The leak was in the retry loop, not the cache."*
The tell is the construction used for rhythm when no contrast exists.

### 10. Rule of three

Lists pad themselves out to three items, whether or not there were three
things to say.

> Our onboarding is fast, friendly, and flexible. New hires gain clarity,
> confidence, and connection from day one.

> New hires get a laptop and a named buddy on day one, and most ship a small fix
> by Friday.

### 11. Elegant variation

A penalty on repeated tokens pushes the writer to rename the same subject every
sentence, until the reader wonders how many people are in the room.

> The mayor opened the meeting. The city's chief executive then walked through
> the budget. The official took questions, and the municipal leader closed by
> thanking residents.

> The mayor opened the meeting, walked through the budget, took questions, and
> thanked residents for coming.

### 12. False ranges

"From X to Y" where X and Y are not endpoints of any scale.

> The festival celebrates everything from the humble sourdough loaf to the
> boundless spirit of community.

> The festival has a bread contest on Saturday and a potluck on the last night.

### 13. Dimensionally false detail

A concrete comparison that is vivid, specific, and the wrong size by an order of
magnitude. It survives review because it reads as *good* writing: the guidance
everywhere rewards the concrete simile over the vague one, and this is a concrete
simile. No regex can catch it. Convert the comparison to a number and check the
number.

> A band of black metal, about as wide as a match is long.

> A band of black metal, no wider than a matchstick.

A match is about forty-five millimetres. The first version describes a ring band
wider than a finger joint, two lines above a sentence saying the ring stops at a
little finger's first knuckle. Three drafting agents, a judge and two editor
rounds all read past it. Where the measurement is load-bearing (evidence in a
mystery, a dosage, a tolerance, a price) this is not a wobbly image; it is the
argument breaking.

---

## Mechanical surface tells

These are the ones `check_ai_tells.py` counts exactly. They are also the ones
most likely to be genuine author habits, so check the baseline before cutting.

### 14. Em dash overuse
Density is the tell, not presence. Commas, colons, or a full stop usually serve.

### 15. Boldface scatter
Bold sprinkled across a paragraph by reflex, so that nothing stands out because
everything does.

### 16. Inline-header bullets
`- **Thing:** restatement of thing`, usually a paragraph wearing a costume.

> - **Onboarding:** Onboarding has been streamlined with a new setup flow.
> - **Reliability:** Reliability has been improved through automatic retries.

> Setup now takes one screen instead of four, and a failed sync retries on its
> own.

### 17. Title Case In Headings
Sentence case reads as human in nearly every context outside a style guide that
demands otherwise.

### 18. Emoji decoration
Emoji as bullet ornaments or heading prefixes. A deliberate emoji in a Slack
message is different; baseline arbitrates this one hard.

### 19. Curly quotes and apostrophes
Typographic quotes where the surrounding surface uses straight ones. A strong
tell in terminals, code, and plain-text email; meaningless in a word processor
that autocorrects. Weigh by destination.

---

## Chat artifacts

### 20. Assistant correspondence
**Watch:** Certainly!, Of course!, I hope this helps, here is a, let me know
if, Would you like me to

The wrapper of a chat reply survives into the document it was meant to deliver.

> Here is a draft of the quarterly update for your team. I hope this helps, and
> let me know if you want the tone adjusted!

> Revenue came in 4 percent under plan, almost all of it from the delayed
> warehouse contract.

### 21. Knowledge-cutoff disclaimers
**Watch:** as of my last update, based on available information, while specific
details are limited

The model's uncertainty about its own sources leaks onto the page as a fact
about the subject.

> While specific details are limited, the bakery is believed to have opened at
> some point in the mid-twentieth century.

> The bakery opened in 1958. The year is carved into the lintel over the door.

### 22. Sycophancy
**Watch:** Great question, You're absolutely right, That's an excellent point

> What a great question, and you're absolutely right to be thinking about this
> now.

> Yes, the lease lets you sublet, but only with the landlord's written consent.

---

## Filler and hedging

### 23. Filler phrases
- due to the fact that → because
- in order to → to
- has the ability to → can
- for the purpose of → for
- in the event that → if
- at this point in time → now
- it is important to note that → (cut it)

### 24. Stacked hedges

> It might perhaps be possible that the delay could somewhat affect some
> deliveries.

> The delay may push some deliveries back a day.

One hedge can be honest and load-bearing. Three in a row is noise.

### 25. Generic uplift

A closing line that could end any piece about anything, because it says nothing
about this one.

> With a passionate team and a clear vision, the sky's the limit. Only time will
> tell what they build next.

> They hire their first two engineers in March.

---

## The other half: adding soul

Strip every tell from a draft and what remains can still read as generated,
because nothing in it sounds chosen. Correct sentences that no one seems to
stand behind are a pattern too, and readers notice it faster than any single
phrase.

When samples are available, they are the source of personality; reuse what the
author actually does. The moves below are how to read a sample for voice, and
the fallback when no sample exists.

**Hold an opinion.** A writer who has looked at the evidence usually thinks
something about it. "I'd ship the smaller fix and argue about the rewrite later"
tells the reader more than a tidy column of advantages set beside a tidy column
of risks.

**Let rhythm follow meaning.** Uniform sentence length is what a generator
produces, but alternation for its own sake is the same mistake wearing a
different hat. A short sentence should carry its weight; a long one should hold a
relationship together that the reader benefits from seeing at once. Vary the
sentences because the thinking varies, never to hit a mix.

**Let complexity stand.** People rarely feel one thing at a time. "It works,
and I resent how long it took us" is truer than "it works."

**Use first person where it fits.** "What I can't get past is the timing"
shows a mind at work on the problem. In most workplace writing that is candor,
not a lapse in tone.

**Allow some mess.** A digression that earns its place, an aside in brackets, a
thought left open at the end of a paragraph: these are how people write when
they are thinking on the page. Symmetry everywhere looks assembled.

**Be specific about feeling.** Not "the new form is frustrating" but "I've typed
my postcode into this form four times, and it has forgotten it four times."

### Clean but soulless

> The four-day week pilot concluded in June. Output remained stable across most
> teams. Some employees reported improved focus, while others found it harder
> to protect their time. Leadership is reviewing the results.

### Has a pulse

> We ran the four-day week for twelve weeks, and I fully expected it to fall
> apart by week three. It didn't. Tickets closed at about the old pace, but
> Thursday afternoons got strange — a sort of quiet panic as everyone tried to
> finish before the long weekend. Most of the team wants to keep it. So do I,
> mostly, though I'd love to know why nobody books a Monday meeting anymore.

Note the second version breaks several rules above: an em dash, a hedge
("mostly") that softens the author's own verdict, and a closing line that
wanders off topic. It is better anyway, because a person is audible in it. That
is the whole point of the baseline rule: these patterns are only tells when
nobody is home.
