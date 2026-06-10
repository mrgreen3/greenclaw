---
name: blog-post
description: Draft and commit a new post to the Zola blog. Use when the user says post or blog about something.
exposes: cc
trigger: /post
locked: true
source: owner
---

Create a new Zola post in the content/ directory of mrgreen3/mrgreen3.github.io as
a .md file with +++ TOML front matter (title, date = today, draft = false). Write
the post from the user's request below, in their voice: dry, hands-on, no filler. Confirm
the title with the user before committing. After committing to main, report the commit URL.
