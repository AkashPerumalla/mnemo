---
name: daily-brief
description: Assemble a short morning brief from stored memories plus live web context.
triggers: morning brief, daily brief, catch me up
---

# Daily brief

1. Call `recall` with "active projects deadlines" and again with "open tasks".
2. For each active project, call `web_search` once for genuinely new developments.
   Skip the search if the project is internal and the web cannot know about it.
3. Write the brief as exactly three sections, no preamble:

   **Today** — at most three things that need the user today, most urgent first.
   **Moving** — one line per active project with what changed since last time.
   **Watch** — anything from the web worth a click, with the URL.

4. Keep the whole brief under 200 words. Cite memory ids and URLs.
5. If a deadline passed with no record of completion, say so first.
