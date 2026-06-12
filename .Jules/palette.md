## 2025-05-14 - [Accessibility] Comprehensive Keyboard Navigation and Focus Management
**Learning:** Interactive elements like recipe cards and selection buttons require explicit ARIA roles and keyboard listeners to be accessible to screen reader and keyboard-only users. Modal focus management is also critical for maintaining context.
**Action:** Always ensure `tabindex="0"`, `role="button"`, and keydown listeners (Enter/Space) are added to custom interactive elements, and manage focus when opening/closing modals.
