---
name: manual-review
description: "Prepare a concise, ordered file-by-file guide for a human manual review."
disable-model-invocation: true
---

# Manual Review

Help the user understand a change by reading its files in a useful order. This
is a review guide, not a findings report and not an implementation task.

1. Establish the review scope from the ref, paths, or working-tree changes the
   user gives. If it is unclear, ask for the intended diff before listing files.
2. Read the changed files and order only the relevant ones from the public
   entry point toward implementation, configuration and infrastructure, data
   migrations, then tests. Group tightly coupled files when that makes the
   review easier.
3. Return a concise numbered list. Each item names a file or group, states its
   role, and says what the reviewer should understand or verify. Use this form:

   `1. [path] — Ruolo: … Verifica: …`

Keep the list focused on how the change works. Do not pre-judge the code or
repeat generic review advice unless the user asks for findings.
