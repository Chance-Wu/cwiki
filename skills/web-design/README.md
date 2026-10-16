# Web Design Skill v1.0

A reusable Web Design Skill for AI coding agents such as Codex, Qoder,
Claude Code, and OpenCode.

## Included

- Core design principles
- Layout / typography / color / spacing / hierarchy / density
- Responsive design
- Interaction and motion
- Developer-tool patterns
- Dashboard / table / detail / settings / command-center patterns
- Anti-AI-slop rules
- Visual review
- Accessibility review
- Responsive review
- New-page and redesign workflows
- Design brief and review templates

## Recommended Usage

Install/copy the `web-design` directory into your agent's skills directory.

The most important workflow is:

```text
Design → Implement → Render → Screenshot → Review → Fix → Render Again
```

The skill is intentionally technology-agnostic, but it prefers reusing the
project's existing stack and design system.

## Suggested Commands

If your agent supports custom commands, map:

- `/design` → workflows/new-page.md
- `/design-review` → review/visual-review.md
- `/design-redesign` → workflows/redesign.md
- `/design-polish` → workflows/visual-iteration.md
