# Security policy

PRAMAAN is a prototype for a regulated field (statutory audit), so its security claims need to be exact. This page says what is protected, what is not, and how to report a problem.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's private reporting instead: the repository's **Security** tab → **Report a vulnerability**. Include:

- what you found and where (file, endpoint or MCP tool);
- steps to reproduce, ideally against the synthetic demo data;
- the impact you expect.

You should get an acknowledgement within 7 days. Please allow a reasonable time for a fix before disclosing publicly. Use only the synthetic demo data while testing, and do not attempt to access data that is not yours.

## Supported versions

Only the latest commit on `main` is supported. There are no maintained release branches yet.

## What is protected

| Area | Control |
|---|---|
| Identity | Bearer credentials are stored only as hashes, expire (15 minutes by default, 30 days at most), and can be revoked. The server never accepts a role from a form or MCP payload. |
| Account sign-in | Optional named accounts: password (scrypt-hashed, at least 12 characters) plus a 6-digit authenticator code (TOTP, replay blocked). Five failures lock the account for 15 minutes, sign-in is rate-limited per address, every error reads the same, and attempts are written to the access log. Sessions last 8 hours and signing out revokes them. Manage with `python -m Pramaan.backend.accounts`. |
| Authorization | Every route maps to a named action, checked against the caller's role on every request, for people and AI agents alike. A per-role SQLite authorizer is a second layer under the API. |
| Human decisions | Final review decisions and confirming an agent's proposal need a separate human-review credential, and are refused on the MCP (AI) channel. |
| Evidence integrity | Every uploaded file is fingerprinted with SHA-256 in a content-addressed vault. The event log is hash-chained and append-only, so editing or deleting history is detected. |
| AI agent | Amounts come only from deterministic tools. Model text is screened for invented amounts and verdict words, party names are masked before anything is sent to the model, and conflicts stop the run. See [docs/AGENT_EVAL.md](docs/AGENT_EVAL.md). |
| Untrusted documents | Document text reaches agents labelled as untrusted content, and instructions inside it are not followed. MCP results are redacted (GSTIN, PAN, account numbers, phone, email). |
| Evidence at rest | With `PRAMAAN_VAULT_KEY_FILE` set (a key kept **outside** the data folder), every vault file is sealed with AES-256-GCM bound to its fingerprint; a missing or wrong key locks the vault (HTTP 503) instead of serving anything. `python -m Pramaan.backend.vault_tools` creates keys and encrypts or decrypts an existing vault safely. Authenticator secrets are sealed with the same key. |
| Backups | `python -m Pramaan.backend.backup create/verify/restore`: a consistent SQLite snapshot plus the vault, in one passphrase-encrypted file (scrypt + AES-256-GCM, tamper and truncation detected), with rotation. Restore verifies every file first and only writes into a new or empty folder. |
| Secrets in the repository | `.env` and AI coding-tool folders (`.claude/`, `.cursor/`, `.gemini/`, `.specstory/`) are git-ignored. The **Secret scan** workflow runs gitleaks over the full history, with extra rules for passwords typed inline in commands, and fails if any of those files is committed. |
| Dependencies | Backend and frontend dependencies are pinned and audited; the current audit reports no known vulnerabilities. |

## What is not protected (known limits)

PRAMAAN is designed for **one company on one machine with synthetic data**. It does **not** provide: multi-tenant isolation, OAuth or SSO, distributed rate limiting (the sign-in limit is per process), database-level grants (PostgreSQL), OS or process isolation, encryption of the SQLite databases themselves (use full-disk encryption such as BitLocker or FileVault; only vault files are encrypted by PRAMAAN), off-site backup scheduling, an external security review, external anchoring of the hash chain, or an official GST/IRP integration (the e-invoice signature check uses a labelled demo key). Do not use it with real client data until these are addressed; see [docs/REMEDIATION.md](docs/REMEDIATION.md).

## Handling credentials

- Give AI agents only `--agent` credentials, and never give them the human-review credential.
- The launcher writes demo credentials to `.demo/runtime/LOCAL_DEMO_CREDENTIALS.txt`; `.demo/` is git-ignored. Do not commit or share that file.
- Keep the vault key and the backup passphrase out of the data folder and out of backups. Losing the vault key makes encrypted evidence unreadable; losing the passphrase makes the backup unusable.
- Keep API keys in `.env` (git-ignored), never inline in commands that a tool might save.
