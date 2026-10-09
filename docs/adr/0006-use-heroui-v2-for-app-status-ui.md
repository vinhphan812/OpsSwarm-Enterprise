# 0006. Use HeroUI v2 for app status UI

Date: 2026-10-08

## Status

Accepted

## Context

Issue #4 binds the scene to Live Twin state, and its review found no loading state, no visible error when the twin cannot be reached, and no handling of a dropped connection. The app also needs a page for unknown routes. Building toasts, spinners, cards, and buttons by hand would cost time that belongs to the twin work.

ADR 0002 keeps the app on React 18 with React Three Fiber 8, because React Three Fiber 9 needs React 19. Options considered:

- **HeroUI 3.x (latest):** needs React 19 and Tailwind CSS 4. Moving to React 19 forces React Three Fiber 9 and Drei 10, which ADR 0002 defers.
- **HeroUI 2.8.10 (last v2):** works with React 18. Needs Tailwind CSS 4 and framer-motion. Ships toasts.
- **Hand-written components:** no new dependencies, but slower and less consistent.

Routing for the 404 page has the same split: React Router 8 needs React 19 and Node 22; React Router 7 works with React 18 and Node 20.

## Decision

Use `@heroui/react` 2.8.10 with `framer-motion` 12, Tailwind CSS 4 through `@tailwindcss/vite`, and `react-router` 7 for routes. Versions are pinned exactly. App code shows toasts through `src/app/notify.ts`, not through HeroUI directly.

## Consequences

- Loading, error, reconnect, and 404 screens use one component kit and Tailwind classes.
- Tailwind's base styles now apply to the whole page.
- HeroUI v2 is the previous major line. Moving to v3 waits for the React 19 upgrade that ADR 0002 already defers, and both upgrades should happen together.
- The JavaScript bundle grows by the component kit and framer-motion.
- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/65
- Issue: https://github.com/vinhphan812/retailtwin-ai/issues/4
- Supersedes:
- Superseded by:
