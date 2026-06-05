## 2026-06-05 - Enhanced Accessibility and Keyboard Navigation
**Learning:** Dynamically rendered recipe cards in this app lacked keyboard interaction, making them inaccessible to non-mouse users. Implementing `role="button"`, `tabindex="0"`, and specific keyboard listeners (`Enter`/`Space`) alongside focus-restoration logic for modals creates a seamless, inclusive experience.
**Action:** Always pair modal-triggering elements with focus-capture and restoration logic, and ensure all custom interactive elements have visible `:focus-visible` styles and semantic ARIA roles.
