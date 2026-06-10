## 2026-06-10 - [Accessibility and Keyboard Navigation Overhaul]
**Learning:** Dynamic elements like recipe cards and modals require explicit focus management and ARIA roles to be usable by screen readers and keyboard-only users. Using `:focus-visible` ensures high visibility for keyboard users without affecting mouse users.
**Action:** Always include `tabindex="0"`, `role="button"`, and appropriate `keydown` handlers for interactive div/article elements. Implement focus restoration for modals using a `lastActiveElement` pattern.
