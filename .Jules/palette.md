## 2026-06-11 - Modal Focus Management
**Learning:** For a truly accessible modal experience, focus must be programmatically managed: capturing the triggering element, focusing the first interactive element in the modal upon opening, and restoring focus to the original element upon closing.
**Action:** Always implement a `lastActiveElement` variable to track and restore focus when dealing with dynamic overlays or modals.

## 2026-06-11 - Accessible Dynamic Cards
**Learning:** Dynamically generated content that is interactive must be explicitly given a role (e.g., `role="button"`), a `tabindex`, and descriptive `aria-label` to be usable by screen readers and keyboard users.
**Action:** In `renderResults` type functions, ensure every generated interactive element has appropriate ARIA roles and keyboard event listeners (Enter/Space) in addition to click handlers.
