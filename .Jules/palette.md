# Palette's Journal

## 2025-05-14 - [Keyboard Accessibility for Dynamic Cards]
**Learning:** In applications where UI elements (like recipe cards) are injected dynamically via JavaScript, standard browser behaviors for buttons (like focus and keyboard activation) are not automatically applied if using non-semantic tags like `div`.
**Action:** Always inject `role="button"`, `tabindex="0"`, and explicit `keydown` listeners (Enter/Space) when rendering interactive dynamic components to ensure they are keyboard-accessible from the moment they appear.
