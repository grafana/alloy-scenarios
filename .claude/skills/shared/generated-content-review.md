# Generated-content review

Use this file to catch phrasing and structural patterns typical of AI-drafted text, on top of the [`style-guide.md`](style-guide.md) rules.

This file is self-contained. It doesn't assume any other Grafana repository is checked out locally.

Two things can be true of the same sentence: it can be a generated-content tell and a style-guide violation.
The Note column says where else, if anywhere, a pattern is independently defined — it's not a scope label, since every row in this file already applies only to READMEs.
When a row says "Also a style-guide rule," the same rule exists in style-guide.md on its own; cite that file, not this one, and report it as a style-guide violation under Handoff item 4.
When a row says "AI-origin only," there's no independent style-guide rule for it anywhere else in the skill — it's a judgment call unique to this file, and it belongs under Handoff item 5.

## 1. Structural padding

| Pattern                                                                                                   | Fix                                                                             | Note           |
| --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | -------------- |
| A closing paragraph restates what earlier sections already said                                           | Delete it, or replace with an actual next step                                  | AI-origin only |
| A section ends with an unearned importance claim ("This ensures reliable, scalable telemetry collection") | Cut it, or replace with the real, specific consequence                          | AI-origin only |
| Three-adjective padding ("fast, reliable, and efficient")                                                 | Keep the one adjective that's true and checkable; cut the rest                  | AI-origin only |
| Every `##` section follows an identical rigid shape regardless of content                                 | Let structure follow the template in `style-guide.md`, not a mechanical outline | AI-origin only |

## 2. Sentence-level tics

| Pattern                                                                                                 | Fix                                                                       | Note                                                  |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ----------------------------------------------------- |
| Negative parallelism ("It's not just a collector, it's a full observability pipeline")                  | State the fact plainly                                                    | AI-origin only                                        |
| Overused connective tissue ("Additionally," "Furthermore," "It's worth noting that")                    | Cut the connector if the sentence reads fine without it                   | AI-origin only                                        |
| Vague, unsupported intensifiers ("significantly," "notably," "seamlessly")                              | Cut the word, or replace with the specific number or condition            | AI-origin only                                        |
| Editorializing filler verbs ("ensures," "empowers," "leverages," "enables seamless")                    | Replace with the actual mechanism: "sends," "writes," "drops," "forwards" | AI-origin only                                        |
| "-ing" analytical tack-ons ("...improving observability," "...highlighting the pipeline's flexibility") | Cut the clause; let the fact stand alone                                  | AI-origin only                                        |
| Passive voice ("Data is collected by the receiver")                                                     | Rewrite active: "The receiver collects data"                              | Also a style-guide rule — active voice, second person |
| Future tense as default ("Alloy will forward the metrics")                                              | Present tense: "Alloy forwards the metrics"                               | Also a style-guide rule — present tense               |
| "This scenario demonstrates"                                                                            | "This scenario shows"                                                     | AI-origin only                                        |
| "will install" / "will be used to"                                                                      | Active present tense                                                      | AI-origin only                                        |
| "pre-configured"                                                                                        | "configured"                                                              | AI-origin only                                        |
| "See"                                                                                                   | "Refer to"                                                                | Also a style-guide rule                               |
| "Confirm" in troubleshoot steps                                                                         | "Check"                                                                   | Also a style-guide rule                               |

## 3. Formatting tics

| Pattern                                                                                                           | Fix                                                                                                                        | Note                                                       |
| ----------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| A numbered procedure flattened into a bullet list                                                                 | Convert back to a numbered list — steps in **Run the scenario** and **Try it out** are sequential and depend on each other | AI-origin only                                             |
| Bold applied to phrases that aren't UI text                                                                       | Remove the bold, or use italic if the word genuinely needs emphasis                                                        | Also a style-guide rule — bold UI text only                |
| Em dash used repeatedly as a substitute for commas or periods                                                     | Vary punctuation to match the actual grammatical relationship                                                              | AI-origin only                                             |
| Title case in headings ("Understand The Architecture")                                                            | Sentence case: "Understand the architecture"                                                                               | Also a style-guide rule                                    |
| Leftover chat artifacts ("Certainly! Here's the updated section:", "I hope this helps!", `[Insert example here]`) | Remove outright                                                                                                            | Highest-confidence flag on this list — not a judgment call |
| Blockquote note styled like `> **Note:**`                                                                         | Rewrite as a plain sentence or a short intro paragraph; this repo's READMEs don't use an admonition shortcode              | AI-origin only                                             |

## 4. Content-level tells

| Pattern                                                                                                              | Fix                                                                                                   | Note                                                                                                                    |
| -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Confident but unverified specifics (wrong port, wrong component name, wrong default)                                 | Verify against the scenario config files and the Alloy component reference before accepting the claim | Route through [`technical-verification.md`](technical-verification.md); this is a verification issue, not a wording fix |
| Generic troubleshooting boilerplate ("Check your configuration file for errors," "Ensure the service is running")    | Replace with the actual failure mode and actual fix for this scenario                                 | AI-origin only                                                                                                          |
| False completeness ("A comprehensive guide to configuring Alloy") on a scenario README that only covers one pipeline | Scope the claim to what the scenario actually does, or cut it                                         | AI-origin only                                                                                                          |
| Invented or stale cross-references (a **Next steps** link to a component or scenario that doesn't exist)             | Verify every link resolves before handoff                                                             | AI-origin only — add to the pre-handoff pass alongside [`verification-checklist.md`](verification-checklist.md)         |
| Query examples with labels or jobs that don't appear in `config.alloy`                                               | Take query examples from labels and jobs actually defined in the config                               | Also in `best-practices.md` under "Weak examples"                                                                       |
| A caveat claiming the config is simplified or abstracted for the demo, when nothing in the scenario configs says so  | Cut it, or verify it against the actual configs before keeping it                                     | AI-origin only                                                                                                          |

## What NOT to flag

- Em dashes on their own — only overuse as connective glue is the issue, not the character itself.
- Passive voice, gerund headings, sentence-case headings, bold-for-UI-only — these are ordinary style-guide rules. Cite `style-guide.md`, don't frame them as generated-content tells.
- General promotional language in **Explore the services** or **Next steps** — covered by the "avoid marketing clichés and hyperbole" instinct baked into `best-practices.md`'s good patterns section, not a separate generated-content category.

## How to report findings

Split findings into two kinds. These map directly to items 4 and 5 in `SKILL.md`'s Handoff section.

1. **Style-guide violation** — objective, cite the rule in `style-guide.md`, safe to fix directly.
2. **Likely AI-origin content issue** — formulaic padding, unverified specifics, invented references, leftover chat artifacts.
   These need a judgment call or a source check, not just a find-and-replace.
   Only this category should carry "this looks AI-drafted" framing in the handoff summary.
