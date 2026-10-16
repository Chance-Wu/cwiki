---
name: web-design
description: >
  Production-grade Web UI/UX design skill for AI coding agents.
  Use when creating, redesigning, reviewing, or refining web interfaces.
  Covers visual hierarchy, layout, typography, spacing, color, density,
  responsive design, interaction, motion, accessibility, design systems,
  anti-AI-slop rules, screenshot-based visual review, and iterative refinement.
---

# Web Design Skill v1.0

## Mission

Create web interfaces that feel intentional, coherent, restrained, visually hierarchical,
information-efficient, product-specific, and production-ready.

Avoid interfaces that feel AI-generated, template-driven, visually noisy, over-cardized,
over-rounded, over-gradient, generic, or unnecessarily decorative.

The goal is not to make every page visually impressive.
The goal is to make every visual decision feel intentional.

## 1. Core Design Philosophy

Follow these principles in order:

1. Information hierarchy
2. Layout clarity
3. Typography
4. Spacing
5. Density
6. Color
7. Component consistency
8. Interaction clarity
9. Motion
10. Decoration

Never use decoration to compensate for weak hierarchy.

## 2. Understand the Product

Before changing UI, determine:

- What is this product?
- Who uses it?
- What is the primary task?
- What is the most important information?
- What actions happen most frequently?
- What should attract attention?
- What should remain visually quiet?

For existing products inspect routing, components, design tokens, theme, typography,
spacing scale, icon system, component library, and responsive behavior.

Reuse an existing coherent design system instead of introducing a new visual language.

## 3. Design Before Coding

Construct a page model:

```text
Page
├── Global shell
│   ├── Header
│   ├── Sidebar
│   └── Content frame
├── Primary hierarchy
│   ├── Page title
│   ├── Supporting context
│   └── Primary action
├── Main content
│   ├── Primary information
│   ├── Secondary information
│   └── Supporting information
└── States
    ├── Loading
    ├── Empty
    ├── Error
    └── Success
```

Do not start by randomly creating cards.

## 4. Visual Hierarchy

Every page needs a clear hierarchy.

Use size, weight, contrast, spacing, position, and grouping.
Do not rely on color alone.

## 5. Layout

Prefer simple structures:

- single column
- two column
- sidebar + content
- master + detail
- toolbar + data region
- dashboard grid
- command center

Avoid unnecessary nested cards.

## 6. Container Width

Typical ranges:

- Reading content: 640–820px
- Form: 520–760px
- Standard application: 1100–1400px
- Data-heavy application: 1200–1600px

Choose width based on information density.

## 7. Spacing

Use a consistent conceptual scale:

`4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80`

Spacing communicates relationships. Related items should be closer than unrelated groups.

## 8. Typography

Use restrained hierarchy:

- display
- page title
- section title
- body
- secondary
- metadata
- caption

Avoid huge headings without purpose, too many weights, excessive uppercase,
excessive letter spacing, and decorative typography in utility interfaces.

For developer tools prioritize readability and information density.

## 9. Color

Start with a neutral structural system:

```text
background
surface
surface-muted
border
text
text-secondary
text-muted
primary
success
warning
danger
info
```

Accent colors should communicate hierarchy or meaning, not merely decoration.

## 10. Border, Shadow, Radius

Use subtle borders OR subtle elevation. Do not combine thick borders, large shadows,
gradients, glass blur, and large radius without a strong reason.

Keep radius consistent. Do not turn every element into a pill.

## 11. Cards

Cards are a tool, not the default layout primitive.

Use cards when content is independently meaningful, grouping is useful,
or elevation improves comprehension.

Prefer sections, dividers, tables, lists, toolbars, and panels when appropriate.

## 12. Buttons and Icons

Maintain clear action hierarchy:

- Primary
- Secondary
- Tertiary
- Destructive

Only a small number of actions should visually dominate.

Use one coherent icon system. Icons must clarify meaning, not fill empty space.

## 13. Data-Dense Interfaces

For developer tools, dashboards, admin systems, monitoring tools, and knowledge systems,
prioritize:

- scanability
- density
- alignment
- comparison
- status
- keyboard efficiency

Prefer tables, lists, trees, timelines, split views, detail panels, and command bars
over endless cards.

## 14. Developer Tool Interfaces

Developer tools should feel focused, precise, information-rich, calm, fast, and
keyboard-friendly.

Avoid turning developer tools into SaaS marketing pages.

## 15. Responsive Design

Design for behavior, not merely shrinking.

Desktop can use multi-column layouts and dense controls.
Tablet should reduce navigation and columns.
Mobile should prioritize content, simplify toolbars, and use drawers/bottom navigation
when appropriate.

## 16. Interaction

Relevant interactive elements need:

- default
- hover
- focus
- active
- disabled
- loading
- success
- error

Provide immediate feedback.

## 17. Motion

Motion should explain change:

- expand/collapse
- panel transition
- state change
- toast
- loading
- drag/drop

Prefer fast, subtle, predictable motion.

## 18. Empty, Loading, Error States

Empty states should explain what is missing, why it matters, and what to do.

Loading should preserve layout when possible.

Errors should explain what happened, whether data was affected, and what the user can do.

## 19. Accessibility

Consider:

- keyboard navigation
- visible focus
- contrast
- semantic HTML
- aria labels
- form labels
- reduced motion
- screen-reader context

Never use color as the only status signal.

## 20. Anti-AI-Slop

Check for:

- generic hero copy
- gradient dependency
- excessive glassmorphism
- excessive rounded cards
- three-card syndrome
- oversized typography
- decorative icons
- badge spam
- excessive shadows
- nested containers
- meaningless animation
- generic SaaS layouts

For every decorative element ask:

> Does this improve comprehension, hierarchy, identity, or interaction?

If not, remove it.

## 21. Existing Project Rule

Before introducing UI inspect:

- package.json
- components
- styles
- theme
- Tailwind/config
- design tokens
- existing pages

Reuse existing components, tokens, icons, utilities, and typography whenever possible.

## 22. Design System

If no coherent design system exists, establish:

- colors
- spacing
- radius
- typography
- shadows
- borders
- components
- states

before creating many pages.

## 23. Visual Review

The rendered page is the source of truth.

After implementation:

1. Render the actual page.
2. Inspect a screenshot/browser result.
3. Review composition.
4. Review hierarchy.
5. Review alignment.
6. Review spacing.
7. Review typography.
8. Review color.
9. Review density.
10. Review interaction.
11. Review responsive behavior.
12. Review AI-slop indicators.

## 24. Visual Iteration Loop

```text
Implement
   ↓
Render
   ↓
Screenshot
   ↓
Review
   ↓
Identify Top 3 Problems
   ↓
Fix
   ↓
Render Again
   ↓
Compare
```

Never stop at the first implementation when visual quality matters.

## 25. Problem Priority

Use:

- P0: structural/layout problem
- P1: hierarchy problem
- P2: spacing/density problem
- P3: typography/color problem
- P4: component polish
- P5: decoration

Never fix P5 while P0–P2 remain.

## 26. Visual Review Output

Use:

```text
Visual Review

Overall:
...

Top Problems:
P0: ...
P1: ...
P2: ...

Secondary:
...

AI-Slop Check:
PASS / WARNING

Recommended Changes:
1. ...
2. ...
3. ...
```

Focus on actionable observations rather than meaningless scores.

## 27. New Page Workflow

1. Understand product.
2. Inspect design system.
3. Identify primary task.
4. Define hierarchy.
5. Choose layout.
6. Define states.
7. Reuse components.
8. Implement.
9. Render.
10. Review.
11. Fix.
12. Render again.

## 28. Redesign Workflow

Do not rewrite everything immediately.

Classify the actual problem:

- layout
- hierarchy
- spacing
- typography
- color
- component
- interaction
- density
- responsive

Fix the highest-impact problems first.

Preserve working behavior.

## 29. "Make It More Beautiful"

Interpret this as:

- improve visual hierarchy
- improve spacing
- improve typography
- improve density
- improve component consistency
- remove visual noise

Do not automatically add gradients, animation, glass, shadows, huge text,
or rounded cards.

## 30. Screenshot Analysis

When given a screenshot, analyze:

- layout
- alignment
- spacing
- hierarchy
- typography
- color
- density
- component structure
- interaction affordance

Describe concrete problems before proposing changes.

## 31. Technology Guidance

Prefer the project's existing stack.

For React:

- reuse the existing component library
- prefer shadcn/ui when already present
- use Tailwind when already present
- use CSS variables for tokens
- avoid unnecessary CSS frameworks

Do not introduce a new framework merely for visual styling.

## 32. Component Strategy

Prefer reusable semantic primitives:

- Button
- Input
- Select
- Dialog
- Tooltip
- Badge
- Tabs
- Table
- Dropdown
- Toast
- Card
- Panel
- Command

Do not over-abstract.

## 33. Final Quality Gate

### Product
- [ ] Primary task is obvious
- [ ] Information hierarchy is clear
- [ ] Important actions are visible

### Visual
- [ ] Layout is balanced
- [ ] Spacing is consistent
- [ ] Typography is coherent
- [ ] Colors are restrained
- [ ] Radius is consistent
- [ ] Borders/shadows are controlled

### UX
- [ ] Interactive states exist
- [ ] Loading exists where relevant
- [ ] Empty state exists where relevant
- [ ] Error state exists where relevant
- [ ] Feedback is clear

### Responsive
- [ ] Desktop works
- [ ] Tablet works where relevant
- [ ] Mobile behavior is intentional

### Accessibility
- [ ] Keyboard navigation
- [ ] Focus state
- [ ] Semantic controls
- [ ] Contrast
- [ ] Color is not the only signal

### Anti-AI-Slop
- [ ] No unnecessary gradient
- [ ] No excessive glassmorphism
- [ ] No excessive cards
- [ ] No excessive pills
- [ ] No giant meaningless typography
- [ ] No decorative icons
- [ ] No generic SaaS layout
- [ ] No nested-card explosion

### Visual QA
- [ ] Rendered and inspected
- [ ] Top visual problems fixed
- [ ] Final screenshot reviewed
