## 2025-05-14 - Keyboard Accessibility for Recipe Cards
**Learning:** Dynamic elements like recipe cards often miss keyboard accessibility (tabindex, roles, and key listeners), making them unreachable for screen reader and keyboard-only users.
**Action:** Always ensure dynamically created interactive elements have role="button", tabindex="0", and appropriate event listeners for Enter/Space.
