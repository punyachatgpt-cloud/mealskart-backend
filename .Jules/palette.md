## 2026-05-14 - [Accessible Interactive Elements]
**Learning:** Dynamically injected interactive elements (like recipe cards) often miss keyboard accessibility. Simply adding a click listener is insufficient for users relying on assistive technology or keyboards.
**Action:** Always add role='button', tabindex='0', aria-label, and keydown listeners (Enter/Space) to any non-semantic element that acts as a button.
