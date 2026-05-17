## 2026-05-17 - [Accessible Modals and Cards in Vanilla JS]
**Learning:** For single-page applications without a UI framework, accessible modals require manual focus management (trapping focus or at least setting/restoring it) and dynamic elements (like cards) need explicit ARIA roles and keyboard listeners to be accessible.
**Action:** Always add `role="button"` and `tabindex="0"` to interactive cards, and ensure modals restore focus to the triggering element upon closure.
