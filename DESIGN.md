# Design contract

Product:        A local review UI for memsift, a memory hygiene tool for coding agents.
Audience:       Developers who already run coding agents and open the UI on 127.0.0.1 after a scan.
Page job:       Show what needs a decision and make the next review action obvious.
5-second:       "This is my agent's memory index, and these findings need a look."
Character:      exact, nocturnal

## Direction

A. Terminal / editorial, with a warm clay accent instead of the usual cold blue.
Why: memsift is a local CLI tool. The UI should feel like the terminal it belongs to, not a SaaS dashboard.

## Type

Display:      JetBrains Mono / IBM Plex Mono / Iosevka stack, weight 500, tight tracking.
Text:         IBM Plex Sans / Golos Text / Source Sans 3 stack, 16px, 68ch measure.
Mono:         ids, paths, counts, scores, timestamps, labels, nav numbering.
Cyrillic:     not required in UI copy, but the font stacks have Cyrillic fallbacks.

## Color

Field:        #0b0c0e
Surface:      #121316
Surface-2:    #18191d
Ink:          #f0ece4
Muted:        #9a948a
Line:         #2a2723
Accent:       #e8703a, used for active nav, primary buttons and health fill.
Status:       conflict #e07a5f, stale #d9a441, orphan #8aa9c0, secret #d97a8a, ok #8fbf8f.
Ratio:        body at least 4.5:1, large text at least 3:1.

## Layout

Grid:         236px rail + minmax(0, 1fr), 12-column content, 1280px max.
Rhythm:       24px inside groups, 48px between sections, 64px page tail.
Radius:       2px.
Surfaces:     hairline borders and background steps, no shadows.
Breakpoints:  360, 600, 900, 1280.

## Content

Headline:     Review your agent's memory.
Subhead:      Duplicates, contradictions, stale references, and secrets. Nothing is written back until you approve it.
Primary CTA:  Open queue.
Proof:        live counts, finding rows, diffs, paths and timestamps from the local index.

## Signature

A numbered left rail with a 20-segment health meter on the dashboard.

## Motion

120ms and 160ms, cubic-bezier(0.2, 0, 0, 1). Hover changes background or border color only. Reduced motion disables transitions.

## Images

No decorative images. The interface itself is the artifact: real findings, diffs, paths, and counts.

## Banned

- radial gradients, glows, glassmorphism
- pill-shaped status badges and 16px radii on everything
- three identical cards in a row
- em dash punctuation in UI copy
- external fonts or assets, the review UI must stay offline
