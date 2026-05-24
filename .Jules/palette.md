## 2025-05-22 - Focus Management in Modals
**Learning:** When using modals for secondary content (like recipe details), focus management is essential for keyboard users. Specifically, focus should move to a primary action (like 'Close') when opened, and return to the trigger element when closed.
**Action:** Always capture the `document.activeElement` before opening a modal to restore it on close.
