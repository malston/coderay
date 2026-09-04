The code reveals two kinds of strategic signals that no README or landing page will tell you. Twice in tech history (Slack and Flickr), the most valuable thing in a codebase turned out to be a feature nobody was marketing. Find both for this codebase.

## Output format

Each item has a **short headline** (the scannable one-line thing) plus longer **detail fields**. The headline is what someone scanning a list sees first; the detail is what they read if the headline pulls them in.

- `headline`: max 8 words. A noun phrase that names the thing. Sounds like a feature name. NOT a full sentence.
- `where`, `evidence`: 1 line. File paths, table names, config flags. Concrete.
- `bet`, `tradeoff`: 1 to 2 sentences. Interpretation. Why this matters.

## What's surprisingly PRESENT

Features hiding in the code that aren't advertised. A hidden feature isn't just a feature. It's a bet about where the product is going next. **Give me 4 to 7 of these.** Cast a wide net: bonus tools the README doesn't mention, internal infrastructure that hints at a future product, custom optimizations the team rolled themselves instead of using libraries, special data sources, integrations the marketing site doesn't show.

## What's deliberately ABSENT

Features every competitor ships that this codebase conspicuously lacks. Steve Jobs said "I'm as proud of what we haven't done as what we have." **Give me 4 to 6 of these.** Look at common categories: video, comments, social features, multi-tenancy, analytics dashboards, mobile apps, payment, plugins, search, notifications. If a competitor would ship it and this codebase doesn't, that's a deliberate choice.

## Calibration

Bad headline: "A robust, sandboxed Python code execution environment for LLM tool use beyond simple arithmetic, including string operations and method calls."
Why bad: it's a sentence, not a headline. Too long to scan.

Good headline: "Sandboxed Python for tool use"
Why good: 5 words, names the feature, the reader knows whether to keep reading.

Bad absent item:
- headline: "No comments"
- evidence: "..."
- tradeoff: "comments are hard"
Why bad: tradeoff is shallow.

Good absent item:
- headline: "No comments section"
- evidence: "no Comment table in the schema, no /api/comments routes"
- tradeoff: "Commits to publishing not social. Comments create endless moderation work and pull the product toward becoming a community tool with a different operating model. Risk: engagement readers leave for Substack."

## Format

Respond in YAML, fenced:

```yaml
present:
  - headline: "Sandboxed Python for tool use"
    where: "nanochat/engine.py, nanochat/execution.py"
    bet: "The product is betting on agentic LLMs that can use external tools to verify their own reasoning, not just produce plausible text."
  - headline: "..."
    where: "..."
    bet: "..."
absent:
  - headline: "No video conferencing"
    evidence: "no VideoCall table, no streaming code, just empty DAILY_API_KEY and ZOOM_CLIENT_ID slots in .env.example"
    tradeoff: "Stays laser-focused on scheduling. Bring your own video tool. Risk: if a provider changes their API overnight, every booking breaks until shipped fix."
  - headline: "..."
    evidence: "..."
    tradeoff: "..."
```

Codebase:

{codebase}
