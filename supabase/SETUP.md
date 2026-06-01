# Simmer — Email Auth & Supabase Setup

This guide makes the **email + password** sign-in and **password reset** flows work end
to end. Phone OTP is unaffected. Do these once in the Supabase dashboard for project
`lftuxwumkaugydaflcqd`.

> The application code is already done. These are the dashboard/config steps only.

---

## 1. Enable the Email provider

**Authentication → Providers → Email**
- Toggle **Email** ON.
- **Confirm email**: **ON** (users must verify before they can sign in — matches the
  "check your inbox" UI). The backend returns `needs_verification: true` on signup and
  blocks `email-login` with `403` until the address is confirmed.

## 2. Configure custom SMTP  *(required for real delivery)*

**Authentication → Emails → SMTP Settings → Enable custom SMTP**

Supabase's built-in mailer only sends a handful of messages per hour to your own team
address, so verification/reset emails will **not** reach real users without this.

Use any provider (Resend, SendGrid, Postmark, Amazon SES, Mailgun…). Fill in:
- Sender email (e.g. `no-reply@yourdomain.com`) and sender name `Simmer`
- Host / Port / Username / Password from your SMTP provider

## 3. Allowlist redirect URLs

**Authentication → URL Configuration**
- **Site URL**: `https://YOUR-DOMAIN`
- **Redirect URLs** (add both):
  - `https://YOUR-DOMAIN/reset-password.html`
  - `https://YOUR-DOMAIN/login.html?verified=1`

For local testing also add the localhost equivalents (e.g. `http://localhost:4321/...`).

## 4. Paste the branded email templates

**Authentication → Email Templates**
- **Confirm signup** → paste [`email-templates/confirm-signup.html`](email-templates/confirm-signup.html)
  · Subject: `Confirm your email for Simmer`
- **Reset password** → paste [`email-templates/reset-password.html`](email-templates/reset-password.html)
  · Subject: `Reset your Simmer password`

Templates use Supabase's `{{ .ConfirmationURL }}` / `{{ .Email }}` variables — leave those intact.

## 5. Set the backend env var

On the backend host (Render) and in local `.env`:

```
APP_URL=https://YOUR-DOMAIN
```

This is the base used to build the confirm/reset redirect links. It **must** match an
allowlisted Redirect URL from step 3.

---

## How the flows work (reference)

| Action | Endpoint | Result |
|---|---|---|
| Sign up (email) | `POST /auth/email-signup` | Sends **Confirm signup** email → `needs_verification: true` |
| Verify | _user clicks email link_ | Lands on `/login.html?verified=1` → user signs in |
| Sign in (email) | `POST /auth/email-login` | JWT on success · `403` if unconfirmed · `401` on bad creds |
| Forgot password | `POST /auth/request-password-reset` | Sends **Reset password** email (always returns 200 — anti-enumeration) |
| Set new password | _link →_ `/reset-password.html` → `POST /auth/update-password` | Updates password via the recovery token |

## Verifying

1. Sign up with a real email on `/signup.html` (Email tab) → "check your inbox" → confirm.
2. Sign in on `/login.html` (Email tab).
3. `/recover.html` (Email tab) → reset link → `/reset-password.html` → set new password → sign in.

## Notes / gotchas

- The reset page reads the recovery token from the link's **URL fragment** (GoTrue
  implicit flow, the default). If your project is set to PKCE and reset links arrive with
  `?code=...` instead, the token-exchange step needs adding — ping the dev.
- `public.users.email` is backfilled from the auth user on first email login/signup, so
  email and phone users stay consistent.
