# Palette's Journal - Critical Learnings

## 2026-05-20 - [Initial Setup]
**Learning:** The application lacks basic keyboard accessibility for dynamic elements and modal interactions.
**Action:** Always ensure dynamic components like recipe cards have appropriate roles, tab indices, and keyboard listeners. Implement focus management for modals.

## 2026-05-20 - [Keyboard Accessibility Pattern]
**Learning:** For dynamic single-page applications, interactive cards and modals must explicitly handle focus and keyboard events to be accessible.
**Action:** Use tabindex="0", role="button", and keydown listeners for Enter/Space on custom interactive elements. Implement focus traps or focus restoration for modals.
