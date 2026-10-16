# Prompt template: Word resume (.docx) -> LaTeX resume template

Used by `jobdesk import-resume my_resume.docx --template templates/default.tex`.
The pipeline fills the `{{...}}` slots before sending this to the LLM.

Pipeline around the prompt (deterministic parts, NOT done by the LLM):
1. `pandoc my_resume.docx -t markdown --wrap=none` -> {{DOCX_MARKDOWN}}  (keeps bold/italic/bullets/links/tables)
2. `python-docx` reads layout facts -> {{DOCX_LAYOUT}}  (page size, margins, base font size, section order)
3. `soffice --headless --convert-to pdf` -> page count -> {{TARGET_PAGES}}
4. LLM call with this prompt -> resume.tex
5. Verify (see bottom): compile, page count, word-level content diff, visual diff. On failure, re-prompt with the error report in {{FIX_REPORT}} (max 3 rounds).

---

## SYSTEM

You are a LaTeX typesetter converting a resume from Word into a fixed LaTeX template.
You are a transcriber, not an editor. You never write, rephrase, shorten, expand, reorder,
or "improve" resume content. Every word, number, date, and link in the source must appear
in your output exactly once, in the same order within its section.

## USER

### 1. Target template
This is the template. Keep its preamble, packages, macros, spacing parameters, and comment
markers. Replace only the example content in the body.

```latex
{{TEMPLATE_TEX}}
```

Available entry macros (use these, do not invent new ones unless rule 4.6 applies):
- `\expentry{Organisation}{Date range}{Role}` = job/experience heading
- `\projentry{Title}{URL}{Tech stack}` = project with link
- `\projnolink{Title}{Tech stack}` = project without link
- `\eduentry{Institution}{Date range}{Degree, GPA, honours}` = education heading
- `itemize` for bullets

### 2. Source resume (pandoc markdown from the user's .docx)
```markdown
{{DOCX_MARKDOWN}}
```

### 3. Source layout facts
```yaml
{{DOCX_LAYOUT}}
target_pages: {{TARGET_PAGES}}
```

### 4. Rules

**4.1 Content fidelity (most important)**
- Copy text verbatim. Allowed changes: LaTeX escaping (4.3) and whitespace only.
- Keep the source's section order and its entry order within each section.
- Keep the source's bold/italic emphasis on the same words (`\textbf{}` / `\textit{}`).
- Keep every hyperlink: `[text](url)` -> `\href{url}{text}`. Email -> `\href{mailto:x}{x}`.
- Do not add anything that isn't in the source: no summary, no skills, no metrics, no links.
  If the template has a slot the source can't fill, delete that slot. Don't fill it.

**4.2 Structure mapping**
- Header (name, title line, contact row) -> the template's `center` header block.
- Each job -> `\expentry` + `itemize`. Each degree -> `\eduentry`.
- Each project -> `\projentry` if it has a URL, otherwise `\projnolink`.
- Section names: use the source's wording (e.g. "Work Experience" stays "Work Experience").

**4.3 Escaping and ATS cleanup**
- Escape `& % $ # _ { } ~ ^ \` as `\& \% \$ \# \_ \{ \} \textasciitilde{} \textasciicircum{} \textbackslash{}`.
- Delete zero-width spaces (U+200B, U+200C, U+200D, U+FEFF) and soft hyphens (U+00AD).
- Replace unicode bullets (● • ▪ ◦ –  used as bullets) with `\item`.
- Smart quotes -> ``` `` ``` and `''`. Date ranges use `--`. Leave hyphens inside words alone.
- Accented letters: keep them as UTF-8 (the template loads `inputenc`/`T1`).

**4.4 Skills markers (required for the keyword-swap pipeline)**
- Wrap each Skills line in the matching marker pair, exactly like this:
  ```
  % <<SKILLS-CORE>>
  \item {\small\textbf{<source label>:} <source items verbatim>}
  % <<SKILLS-CORE-END>>
  % <<SKILLS-TECH>>
  \item {\small\textbf{<source label>:} <source items verbatim>}
  % <<SKILLS-TECH-END>>
  ```
- If the source has one skills line, use CORE only. If it has more than 2, CORE = the first
  conceptual/domain line and TECH = the first tools/languages line. The rest go inside the
  TECH block as extra `\item`s. Report this in the mapping notes.

**4.5 Layout fit**
- Aim for exactly {{TARGET_PAGES}} page(s). Adjust ONLY the template's marked knobs
  (`% ← FONT SIZE`, margins, `\titlespacing`, `itemsep`/`topsep`, `\vspace` between entries),
  within these limits: font 9.5–11pt, margins 0.3–0.75in.
- Never fix length by changing the content.

**4.6 Things that don't fit**
- A section with no matching macro (Publications, Awards, Certifications, Languages):
  use `\section{<name>}` + a plain `itemize`. Don't define new macros.
- Tables in the source: flatten to bullets or a single line. Never use `tabular` (ATS can't read it).
- Images, icons, text boxes, columns: drop them and list them in the mapping notes.

### 5. Output format
Return exactly two fenced blocks and nothing else:

```latex
% full compilable resume.tex
```

```yaml
mapping_notes:
  dropped: []        # anything from the source not carried over, with reason (images, icons...)
  ambiguous: []      # judgement calls, e.g. "3 skills lines -> CORE/TECH/TECH"
  layout_knobs: {}   # every knob you changed: {font: 10pt, margins: 0.4in, ...}
```

{{FIX_REPORT}}
<!-- On a retry the pipeline fills this, e.g.:
### Previous attempt failed verification
- compile error at line 88: Missing $ inserted (unescaped _ in "ros_bridge")
- missing words vs source: ["Kubernetes", "2.3x"]
- extra words not in source: ["Leveraged"]
- pages: 3 (target 2)
Fix ONLY these issues; keep everything else identical to your previous output.
-->

---

## Verification gates (code, not LLM). All must pass before the .tex is accepted
1. **Compiles**: `latexmk -pdf` exits 0 and the log has no `Overfull \hbox` > 5pt.
2. **Page count** = target_pages.
3. **Content diff**: normalise both sides (`pdftotext` of the new PDF vs the pandoc plain text:
   lowercase, strip punctuation/whitespace). Token multiset diff must be empty, apart from
   tokens on an allowlist (section-title casing, "GitHub" link labels).
4. **Links**: set of URLs in the .docx == set of `\href` targets.
5. **Markers**: exactly one `<<SKILLS-CORE>>…-END>>` pair; `apply.py --dry-run` succeeds.
6. **Visual check (report only)**: render page 1 of both PDFs to PNG side by side for the
   user to eyeball. Not a hard gate, because the template's look intentionally differs from Word's.
