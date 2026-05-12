## 2025-05-22 - Keyboard Accessible Dynamic Cards
**Learning:** Dynamically injected elements that function as buttons (like recipe cards) must be explicitly given role='button' and tabindex='0', and require manual keydown listeners for 'Enter' and 'Space' to be fully accessible.
**Action:** Always include keyboard event listeners alongside click listeners when rendering dynamic interactive content.

## 2025-05-22 - Production API Configuration
**Learning:** Avoid hard-coding API base URLs if possible, but if they are already hard-coded to production, revert any local testing changes before submission to prevent infrastructure breakages.
**Action:** Use Playwright's `page.add_init_script` to override variables for testing instead of modifying the source code.
