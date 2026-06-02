# Security

Do not commit API keys or local configuration files.

This project reads credentials from `.env`. Keep `.env` local and commit only
`.env.example`.

If an API key is accidentally exposed, revoke it from the provider dashboard
and create a new key before continuing development.
