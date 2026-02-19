# OAuth Setup Guide

This guide walks through setting up Google OAuth authentication for the Temper AI.

## Table of Contents

- [Prerequisites](#prerequisites)
- [1. Get Google OAuth Credentials](#1-get-google-oauth-credentials)
- [2. Configure Environment Variables](#2-configure-environment-variables)
- [3. Security Verification](#3-security-verification)
- [4. Testing](#4-testing)
- [Security Best Practices](#security-best-practices)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

- Google Cloud Platform account
- Python 3.8+ with `cryptography` package installed
- Access to this project's codebase

---

## 1. Get Google OAuth Credentials

### Step 1.1: Create OAuth 2.0 Client ID

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Select your project (or create a new one)
3. Click **"Create Credentials"** → **"OAuth 2.0 Client ID"**
4. Configure the OAuth consent screen if prompted:
   - User Type: External (for public apps) or Internal (for workspace apps)
   - App name: Your application name
   - User support email: Your email
   - Authorized domains: Your domain (e.g., `example.com`)

### Step 1.2: Configure OAuth Client

1. Application type: **Web application**
2. Name: `Temper AI OAuth Client`
3. Authorized JavaScript origins (optional):
   - `https://yourdomain.com`
   - `http://localhost:8000` (for development)
4. **Authorized redirect URIs** (CRITICAL):
   - Production: `https://yourdomain.com/auth/oauth/google/callback`
   - Development: `http://localhost:8000/auth/oauth/google/callback`

   **SECURITY:** These URLs must match EXACTLY what you configure in `.env`

5. Click **"Create"**
6. **Copy your Client ID and Client Secret** (you'll need these next)

---

## 2. Configure Environment Variables

### Step 2.1: Create `.env` File

```bash
# Copy the example file
cp .env.example .env

# Open .env in your editor
nano .env  # or vim, code, etc.
```

### Step 2.2: Add Google OAuth Credentials

Add the following to your `.env` file:

```bash
# Google OAuth Configuration
GOOGLE_CLIENT_ID=123456789012-abcdefghijklmnopqrstuvwxyz012345.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-YourActualClientSecretFromGoogleConsole
GOOGLE_OAUTH_CALLBACK_URL=https://yourdomain.com/auth/oauth/google/callback
GOOGLE_OAUTH_CALLBACK_URL_DEV=http://localhost:8000/auth/oauth/google/callback
GOOGLE_OAUTH_SCOPES=openid,email,profile
```

**Replace:**
- `123456789012-abc...` with your actual Client ID
- `GOCSPX-YourActual...` with your actual Client Secret
- `yourdomain.com` with your actual domain

### Step 2.3: Generate Token Encryption Key

OAuth tokens are encrypted at rest using Fernet encryption. Generate a secure key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output (looks like: `gAAAAABhS...`) and add to `.env`:

```bash
OAUTH_TOKEN_ENCRYPTION_KEY=gAAAAABhS...YourGeneratedKeyHere
```

**SECURITY:** This key encrypts all OAuth tokens. Keep it secret and rotate every 90 days.

### Step 2.4: Set Environment

```bash
# For development
ENVIRONMENT=development

# For production
ENVIRONMENT=production
```

---

## 3. Security Verification

Run these checks to ensure your OAuth setup is secure:

### Check 1: Verify `.env` is Gitignored

```bash
git check-ignore .env
```

**Expected output:** `.env`

If this fails, your `.env` file might be committed to version control! Remove it immediately:

```bash
git rm --cached .env
git commit -m "Remove .env from version control"
```

### Check 2: Verify No Secrets in Code

```bash
grep -r "GOCSPX-" . --exclude-dir=.git --exclude-dir=venv --exclude=".env"
```

**Expected output:** (empty - only `.env` should contain secrets)

### Check 3: Test Secret Detection

```bash
python -c "
from temper_ai.safety.secret_detection import SecretDetectionPolicy
from pathlib import Path

policy = SecretDetectionPolicy({'allow_test_secrets': False})

# Check .env.example is safe
example = Path('.env.example').read_text()
result = policy.validate({'content': example}, {})
assert result.valid, f'Secrets detected in .env.example: {result.violations}'
print('✓ .env.example is safe (no real secrets)')
"
```

### Check 4: Verify Callback URLs Match

Ensure your `.env` callback URLs **exactly match** what you configured in Google Cloud Console.

```bash
grep "CALLBACK_URL" .env
```

Compare with Google Console → Credentials → Your OAuth Client → Authorized redirect URIs

**SECURITY:** Even a small difference (trailing slash, http vs https, different port) will cause OAuth to fail or create security vulnerabilities.

---

## 4. Testing

### Test 1: Callback URL Validation

```bash
pytest tests/test_auth/test_callback_validator.py -v
```

**Expected:** All tests pass ✅

### Test 2: Token Encryption

```bash
pytest tests/test_auth/test_token_store.py -v
```

**Expected:** All tests pass ✅

### Test 3: Full OAuth Flow (Manual)

1. Start your application
2. Navigate to OAuth login endpoint
3. Click "Sign in with Google"
4. Verify redirect to Google
5. Authorize the application
6. Verify redirect back to your callback URL
7. Verify user is authenticated

---

## Security Best Practices

### 1. Credential Management

**DO:**
- ✅ Store credentials in `.env` file (gitignored)
- ✅ Use different credentials for dev/staging/prod
- ✅ Rotate `OAUTH_TOKEN_ENCRYPTION_KEY` every 90 days
- ✅ Use `${env:VAR}` references in config files

**DON'T:**
- ❌ Hardcode credentials in source code
- ❌ Commit `.env` to version control
- ❌ Share credentials via email/Slack
- ❌ Use production credentials in development

### 2. Callback URL Security

**DO:**
- ✅ Whitelist all callback URLs in `configs/oauth/google.yaml`
- ✅ Use HTTPS in production (enforced automatically)
- ✅ Validate `state` parameter (CSRF protection)
- ✅ Match exact URLs (including trailing slashes)

**DON'T:**
- ❌ Allow arbitrary callback URLs
- ❌ Use HTTP in production
- ❌ Skip state parameter validation
- ❌ Use wildcards or regex in whitelist

### 3. Token Storage

**DO:**
- ✅ Encrypt tokens at rest (automatic with `SecureTokenStore`)
- ✅ Set appropriate token expiry times
- ✅ Implement token refresh before expiry
- ✅ Revoke tokens on logout

**DON'T:**
- ❌ Store tokens in plaintext
- ❌ Store tokens in localStorage (XSS risk)
- ❌ Log tokens (use ObfuscatedCredential)
- ❌ Share tokens between users

### 4. Key Rotation

Rotate your encryption key every 90 days:

```bash
# Generate new key
NEW_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Update .env
sed -i.bak "s/OAUTH_TOKEN_ENCRYPTION_KEY=.*/OAUTH_TOKEN_ENCRYPTION_KEY=$NEW_KEY/" .env

# Restart application to re-encrypt tokens
# (SecureTokenStore.rotate_key() is called automatically on restart if key changes)
```

---

## Troubleshooting

### Error: "Callback URL not in whitelist"

**Cause:** The `redirect_uri` doesn't match your whitelist

**Fix:**
1. Check your `.env` file: `grep CALLBACK_URL .env`
2. Check your config: `cat configs/oauth/google.yaml`
3. Ensure exact match (check trailing slashes, ports, protocols)
4. Restart application after changes

### Error: "Invalid encryption key"

**Cause:** `OAUTH_TOKEN_ENCRYPTION_KEY` is invalid or missing

**Fix:**
```bash
# Generate new key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Add to .env
echo "OAUTH_TOKEN_ENCRYPTION_KEY=<generated-key>" >> .env
```

### Error: "redirect_uri_mismatch" from Google

**Cause:** Callback URL not registered in Google Cloud Console

**Fix:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Edit your OAuth 2.0 Client ID
3. Add the exact callback URL to "Authorized redirect URIs"
4. Save and wait 5 minutes for changes to propagate

### Error: "HTTPS required for callback URLs in production"

**Cause:** Using HTTP in production environment

**Fix:**
1. Update `.env`: `GOOGLE_OAUTH_CALLBACK_URL=https://yourdomain.com/...`
2. Or set: `ENVIRONMENT=development` (only for local dev)

### Error: "Localhost URLs not allowed in production"

**Cause:** Using localhost callback in production

**Fix:**
1. Use your production domain instead of localhost
2. Or set: `ENVIRONMENT=development` (only for local dev)

---

## Configuration Reference

### Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `GOOGLE_CLIENT_ID` | Yes | OAuth 2.0 Client ID from Google Console | `123...apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | Yes | OAuth 2.0 Client Secret | `GOCSPX-...` |
| `GOOGLE_OAUTH_CALLBACK_URL` | Yes | Production callback URL | `https://yourdomain.com/auth/oauth/google/callback` |
| `GOOGLE_OAUTH_CALLBACK_URL_DEV` | No | Development callback URL | `http://localhost:8000/auth/oauth/google/callback` |
| `GOOGLE_OAUTH_SCOPES` | No | OAuth scopes (comma-separated) | `openid,email,profile` |
| `OAUTH_TOKEN_ENCRYPTION_KEY` | Yes | Fernet encryption key for tokens | `gAAAAABhS...` |
| `ENVIRONMENT` | No | Environment name | `development` or `production` |

### OAuth Scopes

Common Google OAuth scopes:

| Scope | Description |
|-------|-------------|
| `openid` | OpenID Connect authentication |
| `email` | User's email address |
| `profile` | User's basic profile info (name, photo) |
| `https://www.googleapis.com/auth/userinfo.email` | Email address (alternative) |
| `https://www.googleapis.com/auth/userinfo.profile` | Profile info (alternative) |

See [Google OAuth Scopes](https://developers.google.com/identity/protocols/oauth2/scopes) for full list.

---

## Support

For issues or questions:

1. Check [Troubleshooting](#troubleshooting) section above
2. Review [Security Best Practices](#security-best-practices)
3. Check Google OAuth documentation: https://developers.google.com/identity/protocols/oauth2
4. File an issue in the project repository

---

## Security Audit Checklist

Before deploying to production:

- [ ] `.env` file is gitignored and NOT in version control
- [ ] Different credentials for dev/staging/prod environments
- [ ] Callback URLs match exactly in Google Console and `.env`
- [ ] HTTPS enforced for production callback URLs
- [ ] Token encryption key is secure and documented
- [ ] All tests pass (`pytest tests/test_auth/ -v`)
- [ ] Secret detection policy passes
- [ ] No credentials in source code or logs
- [ ] Key rotation process documented and scheduled
- [ ] OAuth consent screen configured in Google Console
- [ ] Rate limiting configured (if applicable)

---

*Last updated: 2026-02-01*
