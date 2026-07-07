# Trus V2 — Vision

> Status: founding vision for the **V2** branch. Written 2026-07-06.
> Scope: this document nails down *what Trus is becoming and why*. Go-to-market,
> pricing, target-user sequencing, and the build roadmap are deliberately out of
> scope here — they come next, on top of this.

## North star

**Trus is a personal operating system that composes and runs itself around your
life.** You describe what you need — in plain language, a sketch, or a voice memo —
and a living, always-on environment of apps and agents builds itself around you.
The power of AI automation, minus the plumbing, for everyone.

## The problem

Two graveyards, one root cause — **the setup cliff.**

- **The second-brain / hub graveyard** (synced.it, Notion, quantified-self
  dashboards): they hand you a blank, infinitely-customizable canvas and say *"now
  design your own system."* The average person can't and won't. Customization is
  labor.
- **The AI-automation gap** (Cowork, OpenCLAW, Hermes-style agents, MCP/cron
  setups): real, life-changing power — gated behind AI-literacy. You need to know
  what an MCP, a server, an agent *is*. That's <1% of people.

Trus's answer to both: **the setup burden is the product.** It architects itself;
you tweak. Customization becomes a conversation, not a project.

## The product

**One thing, two faces.** The interface is the *face*; the automation is the
*engine* behind it — never two separate products. Every surface Trus generates can
be alive, backed by an agent underneath, and you only ever see the surface.

- **Self-composing interface** — describe / sketch / voice your needs → a
  personalized, expandable structure appears. The original Trus ethos, ceiling
  raised.
- **The ambition upgrade** — *no more trivial widgets.* Generated artifacts are
  **full, app-like surfaces you zoom in and out of — DOS-grade** — on the spatial
  canvas. The canvas is your **personal-OS home screen**; each portal is an app;
  zooming in *is* launching it.
- **Always-on (literal OS)** — a private per-user runtime. Automations fire 24/7 —
  email triaged, digests compiled, watchers watching — whether or not you've opened
  Trus. **You open it to see what already happened.**
- **Tiered autonomy (the trust spine)** — autonomous for the safe / reversible /
  internal (watch, sort, track, summarize, *draft*); holds for a tap on the
  consequential (send, pay, message a human, delete). A per-automation trust dial
  the user raises as trust grows. *This is the DOS supervisor-loop pattern — already
  built and operated.*
- **Personal-first, shareable surfaces** — the OS is *yours* (profile, sandbox,
  agents). Any single surface can be shared when it's inherently shared: a trip
  board for family, a business dash for a teammate.

## The core loop

```
Describe / sketch / speak your need
  → Trus co-curates the interface + wires the automation
    → it runs always-on with tiered autonomy
      → you open Trus to see what happened & approve what needs a tap
        → refine in plain language
          → (the profile accretes, so next time it's sharper)
```

## The moat

**The sandbox + the accreting profile.** The interface is copyable in a weekend by
a big lab. A private, persistent environment that has known you for two years — your
routines, goals, history, the automations you've come to trust — is not. **The
longer you live in Trus, the more it's worth to leave.** That's the compounding
relationship DOS proved on a sample size of one; V2 generalizes it.

## Positioning

| | They are | Trus is |
|---|---|---|
| synced.it / second-brain | a blank canvas you must architect | an environment that architects itself |
| Cowork / OpenCLAW / Hermes | automation power for the AI-literate | that power, zero plumbing, for the 99% |
| hyperagent | a tool you point at a work task (production) | an environment you *live in* that knows you and acts across your whole life |

## Grounded in what's already built

This is a ceiling-raise, not a rewrite. Already shipped toward it:

- NL + **sketch + voice** input (Stage 2b)
- the **accreting user profile** — the moat (Stage 3/4)
- the **spatial zoomable canvas + page-portals** (Stage 3)
- per-owner isolation + the honesty seam (Stage 1)
- the tiered-autonomy pattern, proven in **DOS's supervisor loop**

## The honest hard parts (what V2 signs up for)

Choosing "literal always-on OS" makes these the whole game, not footnotes:

1. **Per-user persistent runtime** = real infra cost & ops per user.
2. **Holding real credentials** (email, calendar, money) = a serious security +
   liability surface.
3. **Reliability of autonomous action** = existential. One wrong 3am send and that
   user is gone forever.
4. **Integration breadth** = a long tail. "Anything in natural language" collides
   with "we've only connected N services." The connector catalog is a grind.
5. **The tiered-autonomy UI** is subtle — making "what it did / what needs your tap"
   legible and trustworthy is a design problem, not just a backend one.

## Open questions (for the GTM / roadmap pass)

- **Framing** — "OS" is precise but can read as technical to the everyday consumer
  this targets. A warmer consumer-facing name may be worth it.
- **Value capture** — the vision states *what* it sells (easy AI + a friendly skin);
  it does not yet state *how it captures value* (subscription for the always-on
  runtime? usage tiers?). To be settled in the GTM pass.
