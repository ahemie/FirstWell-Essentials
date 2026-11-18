# FirstStep Supabase Auth Setup

1. In Supabase dashboard open Authentication > Users. Invite/create your staff user and verify their email.
2. Copy `.env.example` to `.env` and change `ALLOWED_EMAILS` to your approved staff emails. The app intentionally rejects all logins if no valid allowlist is set.
3. Install: `py -m pip install -r requirements.txt`
4. Run `py app.py` and open `http://127.0.0.1:5501/`.
5. Sign in with the email/password registered in Supabase Auth. Flask checks Supabase Auth, then creates an 8-hour opaque HttpOnly session in local SQLite.
6. Flask protects HTML pages, private data JS/JSON and all `/api` routes. Upload POST requests require a CSRF token. Only an allowlisted, email-verified user can sign in.
7. BACK UP your existing `firstwell.db` and `uploads/` before switching versions. Copy both into this project directory to retain old uploads. Do not commit `.env`, database, or uploaded reports into Git.
8. Supabase public tables remain RLS-enabled and have no access policies: browser clients cannot read them. This update adds authentication to your **local Flask** app; it does NOT migrate your SQLite inventory into Supabase.

**Security limitations:** Server must remain on localhost until you deploy it behind HTTPS with a production-grade session/CSRF configuration and staff role management. Sign-in requires internet access to Supabase. Sessions expire in 8 hours; users sign in again. Flask must not serve `.env`, `.db`, uploaded files or Python source. To revoke a current local session immediately, remove it from `app_auth_sessions` or restart after clearing the table; removing a user from `ALLOWED_EMAILS` blocks subsequent logins but does not invalidate active sessions automatically.
