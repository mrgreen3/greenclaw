---
name: email
description: Read, reply to, or send emails via Gmail. Commands: /email read, /email reply <id> <body>, /email send <to> <subject> <body>
exposes: cc
trigger: /email
locked: false
source: owner
---

The user is asking you to perform an email operation. You have full Gmail MCP access.

**Available operations:**

1. **Read recent emails** — triggered by `/email read`
   - List the last 5-10 unread messages from the inbox
   - Show: sender, subject, preview, timestamp
   - Number them (1, 2, 3, etc.) for reference in follow-up replies

2. **Reply to an email** — triggered by `/email reply <id> <body>`
   - `<id>` is the thread number from the read command
   - `<body>` is the reply text
   - Use Gmail MCP tools to locate the thread and create a reply draft
   - Send the reply automatically

3. **Send an email** — triggered by `/email send <to> <subject> <body>`
   - `<to>` is recipient email address
   - `<subject>` is email subject (if no subject, use empty string)
   - `<body>` is email body
   - Use Gmail MCP tools to create and send the message
   - Confirm after sending

**Important:**
- The inbox address is mrgreen@archbang.org
- Do not ask for confirmation before sending; send immediately and report the result
- Keep replies brief and professional
- If the user's body text contains line breaks, preserve them
- Return a one-line status: what was done, and any key info (recipient, thread ID, etc.)

**Error handling:**
- If a thread or message ID is not found, say so clearly
- If sending fails, report the error and suggest checking the address
