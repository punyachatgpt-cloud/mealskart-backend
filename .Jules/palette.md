## 2025-05-11 - [Dynamic elements accessibility]
**Learning:** Dynamically injected elements like recipe cards are often non-semantic (using <div> or <article>) and missing from the tab order. They need explicit role='button', tabindex='0', and both click/keydown listeners to be truly accessible.
**Action:** Always check render functions for interactive elements and ensure they have necessary ARIA roles and keyboard support from the start.
