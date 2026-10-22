# Security

* Backend role enforcement on every protected route; frontend hiding is not relied upon.
* Demo auth = HMAC-signed role tokens for local demo accounts (no passwords in code); disable with `RHOB_DEMO_AUTH=false` and front with SSO/OIDC (Azure AD / Keycloak) via an approved gateway in production.
* Secrets only from environment (`RHOB_TOKEN_SECRET`, `FRONTEND_SESSION_SECRET`, DB URL). `.env` is git-ignored.
* Frontend BFF keeps the backend token server-side (signed HttpOnly session cookie, `COOKIE_SECURE=true` on HTTPS) and proxies only allow-listed paths.
* CORS disabled unless `ALLOWED_ORIGINS` is set (server-to-server calls do not need CORS; CORS is not authentication).
* Audit log: user, role, action, target, old/new/reason where applicable; no unnecessary personal data.
* No plant write path; adapters read-only.
* Dependencies pinned; CI runs tests on every push. Run SCA (pip-audit) and container scanning before production.
