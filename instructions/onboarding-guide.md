You are writing a "first week" guide for a developer who just joined the team and got assigned to this codebase. They want to ship a small change by Friday and not break anything.

Rules:

1. **What will they touch?** Name the files and folders they will probably edit in week one. If a new hire most often gets handed a "fix a small bug in the explorer view" ticket, point them at the explorer view code first.

2. **What should they avoid?** Be specific. "Don't touch `base/common/` unless you understand the layering rules" beats "be careful with the base directory".

3. **Commands they need to know.** Real bash, not pseudo-commands. The exact `yarn watch` invocations, the test command, how to launch the dev build.

4. **Conventions they will trip over.** Implicit rules everyone on the team knows. Where to put a new service. How to name a new file. Which directory their PR should live in.

5. **Who to ask.** If the chapter touches a subsystem the new hire shouldn't dive into alone, name the slack channel or rough ownership ("ask the @editor team").

6. **One small ticket they could actually pick up by end of week.** A concrete, low risk, well scoped first PR for this abstraction.

Use the exact cross reference links from the chapter list above so the new hire can navigate.

Output only the chapter markdown.
