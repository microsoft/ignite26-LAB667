---
name: skillable
description: "Use when: working on Skillable workshop export, skillable.md, workshop mirroring, Azure Static Web Apps deployment, or the lab530-skillable public repo. Remembers the repository-specific Skillable URLs, generated files, and workflow conventions."
---

# Skillable Workshop Export

Use these repository-specific facts when working on Skillable export and deployment tasks.

## Key Files

- Workshop source files live in `workshop/*.md`.
- `workshop/sync-to-skillable.py` generates `workshop/skillable.md` and `workshop/index.html`.
- `workshop/skillable.md` is generated. Do not hand-edit it unless explicitly requested.
- `workshop/index.html` is generated. Prefer updating `sync-to-skillable.py` and regenerating it.
- `workshop/staticwebapp.config.json` configures Azure Static Web Apps MIME behavior for markdown.

## Skillable Link Format

`skillable.md` entries must use this format:

```markdown
!INSTRUCTIONS[Page Title](https://raw.githubusercontent.com/GlobalAICommunity/lab530-skillable/refs/heads/main/file_name.md)
===
```

Rules:

- The link label comes from the first H1 (`# ...`) in the markdown file.
- Entries are separated by a line containing exactly `===`.
- The base URL is `https://raw.githubusercontent.com/GlobalAICommunity/lab530-skillable/refs/heads/main/`.
- Exclude `skillable.md` itself from generated entries.

## Skillable Markdown Dialect

Skillable uses Markdown, but not every construct behaves exactly like GitHub-flavored Markdown. Treat Skillable-specific syntax as intentional, especially directives such as `!INSTRUCTIONS[...]()` and page separators such as `===`.

Reference docs: `https://docs.skillable.com/docs/creating-instructions-with-markdown-syntax`

Rules:

- Do not "clean up" Skillable directives into normal Markdown links or images.
- Do not replace `===` separators with Markdown headings, horizontal rules, or frontmatter.
- Before adding advanced syntax, callouts, embedded resources, special instructions, or lab-specific formatting, check the Skillable Markdown docs.
- If content must render in both GitHub and Skillable, prefer simple headings, paragraphs, ordered lists, unordered lists, fenced code blocks, and plain links inside the step files.
- For plain folder names, file paths, and UI names in prose, prefer bold text (`**C:\workshop**`, `**.env**`) instead of inline code. Skillable gives inline code a different visual/semantic treatment that reads poorly for this workshop. Refer to the workshop environment file as **.env** once the workspace context is established.
- Keep inline code for actual code symbols, command fragments, environment variable names, literal error messages, and values inside fenced code blocks.
- If a value or symbol in prose is only a visual anchor and does not need to be copied, use bold text instead of inline code, for example **load_dotenv(override=True)**. This includes environment variable names when the attendee is only checking or recognizing them in prose, such as **AZURE_OPENAI_DEPLOYMENT_NAME**. During review, scan workshop prose for inline-code spans and convert every non-copy anchor to bold.
- For larger Python code blocks that attendees copy into files, use `python-notype` as the fenced code block language instead of `python`, for example ```` ```python-notype ````.
- For short explanatory side notes in workshop steps, use Skillable hint callouts with `> [!Hint] hint text here.`.

## Workshop Step Structure

For numbered workshop step chapters, the first content after the H1 must be one short paragraph that explains both:

- The goal of the exercise.
- Why that exercise matters in the larger agent-building flow.

Keep this paragraph plain and direct. Do not start these chapters with code, lists, screenshots, or setup details before the goal/why paragraph.

## Instruction Clarity

Workshop attendees should never have to infer which file they are editing or where a snippet belongs. Be very specific in every step:

- Name the exact file to open or create, for example **agent.py**, **log.py**, or **.env**.
- Say where the file should be located, usually **C:\workshop** or next to **agent.py**.
- When creating a helper file, explicitly say to paste the full helper code into that helper file and save it.
- When returning to the main agent, say "Go back to **agent.py**" before showing imports or integration code.
- For imports, say where they go, for example "At the top of **agent.py**, with the other imports".
- For code inside `main()`, say the nearby anchor, for example "after the MCP tool is connected and before the `Agent(...)` is created".
- For updates to an existing object like `Agent(...)`, say to keep the existing lines and add or replace only the specific line shown.
- After a code change, include a concrete checkpoint that tells attendees what to run and what they should see.

Prefer slightly more explicit instructions over terse labels like "Import the helpers:" when a learner could lose their place.

## Deployment Model

The workshop no longer uploads markdown to Azure Blob Storage. Do not reintroduce `.env`, Azure Storage connection strings, or blob upload code for this flow.

The deployment flow is:

1. `workshop/sync-to-skillable.py` generates `skillable.md` and `index.html` locally.
2. `.github/workflows/mirror-workshop.yml` mirrors the contents of `workshop/` to the public repo `GlobalAICommunity/lab530-skillable`.
3. Skillable consumes the raw GitHub URLs from that public repo.

## GitHub Actions

- The mirror workflow uses `cpina/github-action-push-to-another-repository@main`.
- The mirror token secret is named `WORKSHOP_MIRROR_TOKEN`.
- The destination repo is `GlobalAICommunity/lab530-skillable`.
- The destination branch is `main`.

## Before Finishing Changes

Always review the updated workshop content before finishing:

- Check whether a short note, hint, example, or screenshot placeholder would make the step clearer for the attendee.
- Check whether background context would help the attendee understand why they are doing the step, without turning the workshop into reference documentation.
- Check whether each instruction can only be interpreted one way. If a learner could reasonably choose the wrong file, location, order, value, or action, rewrite the instruction to remove that ambiguity.

When changing workshop filenames, H1 titles, or the generator:

```bash
cd workshop && python sync-to-skillable.py
```

Then verify `skillable.md` uses the raw GitHub base URL and the `!INSTRUCTIONS[...]` format.

Also verify any Skillable-specific Markdown still follows the Skillable documentation, not just GitHub rendering.
