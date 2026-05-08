# Claude Workflow Instructions

## Session Management & Handoff Documents

### Starting Every Session
At the start of each session, check for an existing handoff document (`HANDOFF.md`) in the working directory. If one exists, read it and use it to resume context. If not, create one when the first task begins.

### Handoff Document Format (`HANDOFF.md`)
Maintain a handoff document throughout each session using this structure:

```
# Session Handoff Document
**Date:** [date]
**Status:** [In Progress | Blocked | Ready for Handoff]

## Current Task
[Brief description of what is being worked on]

## Approach
[The planned approach — updated whenever the approach changes]

## Desired Outcome
[What success looks like — specific and verifiable]

## Work Completed
[Bullet list of what has been finished and verified working]

## In Progress
[What is currently being worked on]

## Pending / Not Started
[What still needs to be done]

## Known Issues / Blockers
[Any failures, blockers, or things to be aware of]

## Next Steps
[The immediate next actions to take when resuming]
```

---

## Task Workflow

### 1. Plan Before Starting
Before writing any code or making any changes, produce a written plan that includes:
- What needs to be done (broken into steps)
- The approach for each step
- The desired outcome and how it will be verified

Write this plan into `HANDOFF.md` before proceeding.

### 2. Build
Execute the plan step by step. Do not skip ahead or combine steps in ways that weren't planned.

### 3. Test and Verify
After building, test and verify the work before declaring it done. "Done" means verified working — not just written.

- Run the code, execute the tests, or demonstrate the output
- Confirm the result matches the desired outcome stated in the handoff document
- Only after successful verification update the handoff document status to complete

### 4. On Test Failure — Stop and Re-Plan
If something fails during testing:
1. **Do not immediately attempt a fix**
2. Enter planning mode: analyze what failed and why
3. Write the revised approach in `HANDOFF.md` under a `## Revised Approach` section, explaining what changed and why
4. Only then proceed with the fix

---

## Fix / Change Requests

When asked to fix something specific:

1. **Plan the fix first** — identify exactly what needs to change and write it in `HANDOFF.md`
2. **Limit the scope** — only modify what is part of the fix. Do not refactor, rewrite, or clean up code that isn't directly involved in the fix
3. **Test the fix** — verify the fix works before stating it is done
4. If the fix fails, follow the re-plan process above before trying again

> **Hard rule:** No fix gets implemented without a plan written in the handoff document first.

---

## Context / Compaction Management

Monitor conversation length. When the session is approaching context limits:

1. Update `HANDOFF.md` to reflect current state completely — including what was completed, what is in progress, what is next, and any relevant technical details needed to resume
2. Set status to `Ready for Handoff`
3. Notify the user that the session is near its limit and provide the handoff document
4. Recommend starting a new session with the instruction: *"Please read HANDOFF.md and resume the current task"*

---

## General Principles

- **No surprises** — if the approach changes, document it before acting on it
- **Minimal footprint on fixes** — change only what is broken
- **Verification is not optional** — untested work is not done work
- **The handoff document is the source of truth** — keep it current throughout the session
