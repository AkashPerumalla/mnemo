---
name: research-note
description: Research a topic with live sources and file the conclusion into memory.
triggers: research, look into, dig into, what is the state of
---

# Research note

1. Call `recall` on the topic first. Say plainly what is already known so the
   user is not told things they told you.
2. Call `web_search` two or three times with *different* angles, not rephrasings
   of the same query. Prefer primary sources over summaries.
3. If the sources disagree on anything that matters, call `think_harder` with the
   conflicting claims and let the reasoning model resolve it.
4. Answer in this shape:

   **Short answer** — two sentences, no hedging.
   **What the sources say** — bullets, each with a URL.
   **Open questions** — what is still genuinely unclear.

5. Call `remember` once with the single most durable conclusion, kind `note`,
   tagged with the topic. Do not save the whole write-up.
