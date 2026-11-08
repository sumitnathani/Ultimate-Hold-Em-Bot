# WEBSITE_BUILD_SPEC — the Ultimate Texas Hold'em landing page

> Companion file: [`WEBSITE_SESSION_NOTES.md`](WEBSITE_SESSION_NOTES.md) — the
> working log. **Read both before touching `site/`.** This file is the settled
> brief; the notes are where the build actually stands.
>
> This workstream is **independent of `decision/`**. Nothing here edits the
> engine, its build spec, or the root `SESSION_NOTES.md`. Everything the page
> says about the engine is *read from* the engine.

---

## 1. What this is

A single static HTML page — the front door to the project. Most people will see
it **before** they ever open the GitHub repo, so it has to work as a complete,
self-contained experience: explain what the engine is, earn genuine interest
through the scroll itself, land the honest twist, and only then point at the
repo as the place to go deeper.

The repo is the destination the page builds toward, not a prerequisite for
understanding it. Someone with zero prior context should finish the scroll
understanding the project and impressed by it.

**One file, no build step, no backend, no framework.** GSAP + ScrollTrigger for
scroll-driven motion, Lenis for smooth scrolling, both from a CDN. Everything
else — layout, type, the cards, the motion — is hand-written.

---

## 2. The creative direction, and why

### What was on the table

Five directions were floated before this build (A "It Refuses To Guess", B "The
Correction Log", C "The Best Hand Nobody Wants", D "1 in 156", E "The Overheated
Sell"), with a standing recommendation of **C as spine + D as closing + E's drain
as the bridge**. That recommendation was taken as input, not as an answer.

### The call

**C is the spine. D is the fourth act. B is folded in as a texture, not an act.
E is dropped. A becomes the second act.**

The reasoning, stated plainly because this is the decision everything else hangs
off:

**E is wrong for this material, and it was the one recommendation worth
overriding.** "The Overheated Sell" needs the page to open by performing hype and
then dismantle it. But the project's single best asset is that its most
counterintuitive fact is *already* the honest pitch — you are holding 2♣3♦, the
board is a royal flush, you cannot win a single one of the 990 possible dealer
holdings, and the correct play is to bet. That opening does the work hype would
have done, and it does it with a true statement instead of a false one. Fake
enthusiasm followed by a confession is a trick; opening on the strangest true
thing in the repo and letting the reader work out why is not. The register stays
literary and level throughout, and the twist lands as a **revelation in content**
rather than a **switch in tone**.

**B is not an act, it is a texture.** "The Correction Log" is a strong
credibility engine but a weak spine: a page whose structure is a list of bugs
makes the project sound fragile, and it front-loads self-criticism before the
reader has any reason to care. Instead the corrections are *distributed* to
where they do the most work — the 2.7-second trap sits inside the exactness act
(it is the reason exactness is not paranoia), and the one unfixed bug sits at
the very end, as the last beat before the repo link.

**A is the second act, not the first.** The cost of exactness is the natural
"how does it work" act, and it only means anything once the reader has seen a
decision they cannot explain. Act I poses the puzzle; Act II pays for the
answer.

### The through-line

The page never argues that the engine is impressive. It shows a series of true,
strange, specific numbers and lets them accumulate into the only conclusion
available: **this thing is exact, it is honest about its own errors, and it
still loses — because the loss is the game, not the engine.** The final act is
not a twist ending so much as a bill arriving.

---

## 3. Art direction

The constraint: **no generic "AI-generated site" language.** No purple/violet
gradients, no glassmorphism, no Inter, no floating 3D card clichés, no stock
particles. The page should look art-directed by a person with taste.

### The organising idea

**The page is set, not designed.** It borrows from print: a technical manual, a
ruled specimen sheet, the marginalia of a ledger. Structure comes from hairlines
and the left rail, not from cards-in-boxes and drop shadows. The only "image" in
the whole document is a playing card.

### Type

| Role | Face | Why |
| --- | --- | --- |
| The page speaking | **Instrument Serif** (roman + italic) | Editorial, high-contrast, a little literary. Italic is the *voice*; roman is the *fact*. |
| The engine speaking | **JetBrains Mono** | Everything the engine computed — EVs, counts, verdicts — is set in mono, tabular. |
| Labels | **Archivo** (small, letter-spaced caps) | Interface furniture only, never at display size. |

The semantic split matters: **serif = the page, mono = the machine.** A number
in mono is a number the engine produced; a number in serif is the page talking
about it. This is why the big act numerals are set in serif rather than as
"data" — they are the page's own voice counting its sections.

Deliberately *not* Inter, and Archivo is never used for anything a reader is
meant to feel something about.

### Colour

**Monochrome, with exactly two accents, both of which mean something.**

| Token | Value | Meaning |
| --- | --- | --- |
| `--ground` | `#08090a` | Graphite ground — a dark room |
| `--bone` | `#f2f0ea` | Bone light — the page's ink |
| `--ash` | `#969ea6` | Secondary text |
| `--ice` | `#cfe2dc` | **The engine.** Faint verdigris, used only on values the engine produced. |
| `--card-red` | `#c2312c` | **The deck.** The only warm chroma on the page. |

The discipline is the point: **the interface stays monochrome and the deck owns
the colour.** Red appears only on a card, or on a numeral that is literally part
of a hand. Losses are never red; a loss is shown by a hairline going the other
way.

### Motion

Motion is a language, not a garnish — **every animation has to mean the thing it
is animating.** No universal fade-up-on-scroll.

| Verb | Where | What it means |
| --- | --- | --- |
| **Deal** | Act I | A card arrives into the place held for it |
| **Accumulate** | Act II | A count climbing as the outcome space fills |
| **Rule** | Act III | A row of type rules in and locks, like a compositor setting a line |
| **Trace** | Act IV | A single hairline drawing a path — the walk of a bankroll |
| **Stop** | Act V | Almost nothing. One line draws and halts. Stillness is the verdict. |

Cards breathe very slightly when the viewer is idle, so the page is never dead
on a still screen. `prefers-reduced-motion` collapses the whole thing to a
stacked, complete, readable document — the content is never motion-gated.

---

## 4. Structure

Six movements. Each is a real claim, and every number in every one of them is
reproduced by [`verify_claims.py`](verify_claims.py) against the live engine.

### Act I — The Anti-Hero Hand *(built)*

2♣3♦ on A♠K♠Q♠J♠T♠. All 990 possible dealer holdings play the same royal, so the
player wins **none** of them: equity **0.0000%**, push rate **100%**. EV of
betting **0.0000** against EV of folding **−2.0000**. The engine bets.

Thesis in one hand: **it was never asked whether you win.**

### Act II — The Cost Of Not Guessing

The engine refuses to sample. Where a street can be enumerated, it is:

| Street | Space | Method | Cost |
| --- | --- | --- | --- |
| River | 990 dealer hands | exact enumeration | milliseconds |
| Flop | 1,081 runouts × 990 = **1,070,190** | exact enumeration | **~8.3 s** |
| Pre-flop | no closed form | **2,000,000** runouts + 6,000 boards × **169** classes | **~4 h** to build the table |

Then the trap, which is why the paranoia is earned: the *wrong* flop
enumeration runs in **2.7 s**, looks correct, and reported a **55% push rate on
a hand whose true rate is 14%**. It was caught only by an independent Monte
Carlo cross-check, which now lives in the test suite permanently.

### Act III — The Ladder

Real `decide()` output, in ascending order of how much the hand deserves the
verdict it gets:

| Hand | Board | Verdict | EV bet | EV fold | Margin |
| --- | --- | --- | --- | --- | --- |
| A♣ K♦ | Q♠ J♥ 8♦ 4♣ 2♥ | **BET** | −1.4859 | −2.0000 | +0.5141 |
| A♥ K♥ | Q♥ J♥ 2♣ 7♦ 9♠ | **BET** | −1.5343 | −2.0000 | +0.4657 |
| 7♣ 2♦ | K♠ Q♥ J♦ 8♠ 3♣ | **FOLD** | −2.2899 | −2.0000 | −0.2899 |
| 9♥ 9♦ | K♠ Q♥ J♦ 4♣ 2♠ | **BET** | −0.4495 | −2.0000 | +1.5505 |
| 2♣ 3♦ | A♠ K♠ Q♠ J♠ T♠ | **BET** | +0.0000 | −2.0000 | +2.0000 |
| 7♥ 7♦ | 7♠ 7♣ 2♦ 9♥ 4♣ | **BET** | +12.0000 | −2.0000 | +14.0000 |
| A♠ 2♦ | K♠ Q♠ J♠ T♠ 9♣ | **BET** | +502.0000 | −2.0000 | +504.0000 |

Ace-high with no pair is a **bet** — you expect to lose 1.49 units, and folding
loses 2. The only fold in the ladder is total air, and it wins by **0.29 units**.
A made pair is still a losing bet, just a less losing one.

Plus the folk-wisdom beat, which is real and comes straight out of the table:
poker players call **7♠2♦** the worst hand in the game, but **3♠2♦** wins *less
often* (29.2% vs 31.7%) while **7♠2♦** is worth *less* (−0.96 vs −0.93 units).
There are two different answers to "worst" and the engine only cares about one.

### Act IV — 1 In 156

σ ≈ **4.2 units** of swing per hand against an edge of **0.027 units**. One part
signal to **156** parts noise.

Over 20,000 pooled hands the simulation realised **+0.0036 units/hand — a
profit** on a game that loses. The headline run went broke at **hand 81**. The
deep run, at 800 antes, went broke at **hand 4,990**. At 40 antes, **8 of 10**
bankrolls were gone.

| Stack | Example | Ruin over 10,000 hands |
| --- | --- | --- |
| 40 antes | 50,000 chips | ~97% |
| 400 antes | 500,000 chips | ~57% |
| 800 antes | 1,000,000 chips | ~17% |
| 1,200 antes | 1,500,000 chips | ~2% |

You cannot tell skill from luck at any sample size you will actually play.

### Act V — The Verdict

**−2.70% ± 0.76%** of an ante per hand, over 35,000 simulated hands. The
published optimal figure is **−2.185%**. The gap is **0.68σ**.

It does not beat the house. Nothing beats this game. The edge is in the rules.
Optimal play here means **losing the least**.

Closing beat — the honest one: the engine's numbers are exact, and its
*reporting layer* still has a known wart. `format_report` keeps playing past
ruin, so a broke run's "final bankroll" is meaningless; it once printed
**"profitable trials 7 of 10" when 8 of 10 had gone broke**. It is documented at
the bottom of the README and it is not fixed. See §7.

### Coda — The Repo

The link. Plain, last, quiet.

---

## 5. Technical

- `site/index.html` — one file. No build step, no bundler, no dependencies
  beyond three CDN scripts.
- GSAP 3.12.5 + ScrollTrigger (cdnjs), Lenis 1.1.14 (unpkg). Pinned versions.
- Fonts from Google Fonts.
- **No backend, no analytics, no tracking, no external requests** beyond the
  above.
- Degrades to a complete, stacked, readable document with no JS, no GSAP, or
  `prefers-reduced-motion`. The readout shows the real answer, never
  placeholders.
- Verified with **DOM-measurement probes**, not screenshots — a headless
  browser injects JS that reads `getBoundingClientRect()`, computed styles and
  overflow, and reports text. Screenshot/vision review is explicitly out of
  bounds (it has repeatedly hit a 5 MB message limit and killed sessions).

## 6. Sourcing rule

**Every number on the page is reproduced from the engine by
`site/verify_claims.py`.** If a figure cannot be regenerated from the repo, it
does not go on the page. Figures are quoted from `README.md`,
`SESSION_NOTES.md`, and live `decide()` calls — never from memory or from the
brief that commissioned this build.

Corrections found while sourcing (all folded in, all logged in the session
notes):

- Act I's copy called 2♣3♦ "the second-worst of all 169 starting hands". By the
  engine's own table it is **the worst by win rate** (29.23%) and second-worst
  by `check_value`. The copy now states the win-rate fact, which is stronger and
  exactly checkable.
- The "six classes inside the noise" figure in the README uses
  `|margin| < 1×SE`. The tier-2 *rule* the notes describe is `|margin| < 3×SE`,
  which selects **20**. The page avoids quoting a count.

## 7. Open values question — flagged, not decided unilaterally

**Should the page name the one unfixed bug?** Act V ends on
`format_report` misreporting ruined runs. Arguments both ways are real, so this
is recorded rather than buried:

- *For:* the bug is **already public** in `README.md` under "Known limitations"
  and in the root `SESSION_NOTES.md`. Putting it on the page discloses nothing
  new. The page's entire thesis is that this project tells the truth about
  itself, and a page that claims honesty while quietly omitting the one live
  defect would be the exact failure mode it is warning about. It is also the
  most memorable beat available.
- *Against:* a public landing page is not a bug tracker, and a reader with no
  context may read "unfixed bug" as "unreliable project" rather than as the
  confidence signal it is meant to be.

**The build takes the "for" position**, because the disclosure is already public
and because omitting it would contradict the page's own argument. **This is
reversible in one edit** — if the call goes the other way, cut the closing beat
of Act V and end on "optimal play means losing the least". Owner has been told.

## 8. Out of scope

- Any change to `decision/`, `tools/`, `tests/`, `README.md`, or the root
  `SESSION_NOTES.md`.
- The perception and action layers — not built, not planned, not mentioned.
- Deployment, hosting, custom domain. The page is a file.
