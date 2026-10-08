# Writing style

How text in this repository is written: README, docs, code comments, commit messages, issues and pull requests. Read it before writing anything.

## Voice

- Write as Isma, a climate scientist explaining her own side project to a colleague. First person plural ("we use") or plain statements.
- Say what was done and what came out. Numbers over adjectives.
- Short sentences, ordinary words. If a sentence works without a word, drop the word.
- Be honest about limits in one sentence, then move on.

## Length

- README: what it is, how to run it, current result. One screen if possible.
- A doc page answers one question. Aim for under 400 words; tables beat paragraphs.
- Commit message: a subject line under 70 characters, then a few lines on why, if needed.
- Issues and pull requests: a few short paragraphs, under 200 words.
- Code comments only where the code cannot say it (a unit, a reason, a source).

## Do not

- No em dashes or en dashes. Use commas, colons, brackets or a new sentence.
- No run-in labels: a bold or plain word followed by a full stop at the start of a line ("Speed. ...", "**Checks.** ..."). Use a heading or a normal sentence.
- No stacks of bold, no emoji, no "Key takeaways", "In summary", "It is worth noting".
- No stock phrases: delve, unravel, nuanced, comprehensive, robust, seamless, leverage, underscore, shed light on, game changer, crucial, pivotal.
- No mention of AI tools anywhere, no Co-Authored-By or "Generated with" lines.
- No hype ("powerful", "cutting edge"). The results speak.

## Examples

Good: "SOLWEIG-GPU now runs on Apple Silicon GPUs. A day for a 700 x 700 tile takes 2.2 min on MPS and 2.8 min on the CPU."

Not like this: "**Speed.** We leverage a comprehensive, robust approach that seamlessly accelerates the pipeline."

## Before committing

```bash
grep -rnP "[\x{2013}\x{2014}]" --include="*.md" --include="*.py" . --exclude-dir=.venv --exclude-dir=external
```

and read the text once out loud.
