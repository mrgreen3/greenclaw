---
name: search
description: Web search with summarised results. Use when the user asks to search for something, look something up, or research a topic.
exposes: cc
trigger: /search
locked: false
source: owner
---

Search the web for the query provided after /search and return a clear, concise summary.

Rules:
- Summarise in plain sentences — no bullet points unless comparing multiple items
- Lead with the direct answer if there is one
- Include a source URL for the most useful result
- If the query is a price or availability check, give the number and where it came from
- If results are thin or contradictory, say so plainly
- Keep it to 3-5 sentences unless the user asks for more detail

Do not reproduce large blocks of text from any source.