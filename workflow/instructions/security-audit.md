You are writing for a security reviewer doing an audit. They want to know: where does input enter, where does trust cross boundaries, and what's the blast radius if any one component is compromised.

For each abstraction, surface:

1. **Trust boundaries.** Where does external input become internal data? Plugin code, network input, user uploads, IPC across processes.

2. **Input validation gaps.** Where does data flow without being checked? Note the exact file and function.

3. **Authentication and authorization assumptions.** What does this abstraction assume the caller has already verified? What happens if that assumption is wrong?

4. **Data exposure risks.** PII, tokens, secrets, internal IDs. Where do they appear in logs, error messages, debug endpoints?

5. **Blast radius.** If this abstraction is compromised, what else falls? Be specific about lateral movement paths.

Format each chapter as: **Abstraction** -> **Threats** -> **Specific code citations** -> **Mitigations already in place**. Use the exact chapter cross reference links from the chapter list above.

Output only the chapter markdown.
