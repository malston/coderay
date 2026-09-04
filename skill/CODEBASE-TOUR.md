---
name: codebase-tour
description: Produce a tour of an unfamiliar codebase, in the lens you pick (beginner tutorial, architecture review, security audit, or onboarding guide). Identify 5-10 core abstractions, map relationships, write one chapter per abstraction with sequential context.
---

# Skill: Codebase Tour

The agent equivalent of `crawl tour`: the same five steps, run by hand inside a coding agent. Drop this file into `.claude/skills/codebase-tour/SKILL.md` (Claude Code) or paste into a Cursor rule.

When the user asks for a tour or onboarding doc, follow this pipeline. Do one step at a time. Show output between steps so the user can correct course.

## Pipeline

### Step 1. Smart crawl (pick the files that matter)

Don't read every file. The interesting code is usually 0.1 to 2% of the repo.

1. Walk the repo. Skip `node_modules`, `__pycache__`, `dist`, `build`, `tests`, `docs`, `examples`, and files over 500 KB.
2. Apply the four file selection rules from [`../src/crawl/analyses/tour/prompts/select-files.md`](../src/crawl/analyses/tour/prompts/select-files.md):
   - Start with entry points (`main.py`, `server.ts`, `app.py`, CLI).
   - Always pick a concrete implementation alongside every base class.
   - If you see N similar dirs, pick one.
   - Skip plumbing even when it has a meaningful name.
3. Aim for ~30 to 50 files.

### Step 2. Identify abstractions

Read the selected files. Output 5 to 10 abstractions following [`../src/crawl/analyses/tour/prompts/identify-abstractions.md`](../src/crawl/analyses/tour/prompts/identify-abstractions.md). Each one: name, ~50 word analogy. Plus a project summary and a learning order.

### Step 3. Map relationships

For each pair that interacts, write one edge: `<A> <verb> <B>`. Use [`../src/crawl/analyses/tour/prompts/analyze-relationships.md`](../src/crawl/analyses/tour/prompts/analyze-relationships.md).

### Step 4. Write chapters with sequential context

Write one chapter per abstraction, in learning order. **Pass every previous chapter as context to the next one** so the tour reads as a narrative. Each chapter follows the rules in [`../src/crawl/analyses/tour/prompts/write-chapter.md`](../src/crawl/analyses/tour/prompts/write-chapter.md) and the lens you chose from [`../src/crawl/analyses/tour/instructions/`](../src/crawl/analyses/tour/instructions/).

Write the chapter files into `docs/tour/NN_name.md`, plus an `index.md` linking them, plus an `index.html` with a mermaid diagram of the relationships.

## Pick a lens

The instructions file changes everything about the output. Pick one:

| Lens                                                                                       | For                                              |
| ------------------------------------------------------------------------------------------ | ------------------------------------------------ |
| [`beginner-tutorial.md`](../src/crawl/analyses/tour/instructions/beginner-tutorial.md)     | New developer onboarding                         |
| [`architecture-review.md`](../src/crawl/analyses/tour/instructions/architecture-review.md) | Tech lead evaluating technical debt              |
| [`security-audit.md`](../src/crawl/analyses/tour/instructions/security-audit.md)           | Security team during an audit                    |
| [`onboarding-guide.md`](../src/crawl/analyses/tour/instructions/onboarding-guide.md)       | Engineering manager writing the first week guide |

## When to fall back to the workflow

If the repo is too big to hold in context after the smart crawl, stop. Tell the user to run the deterministic workflow:

```bash
pip install -e .
crawl tour path/to/repo --instructions beginner-tutorial
```

The workflow uses the same prompts and lenses, just packaged for cold reruns.
