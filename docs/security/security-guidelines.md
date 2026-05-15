# Security Guidelines

This document defines security rules that every piece of code in this project must follow. Reviewer agents must enforce these rules without exception. Many of these correspond to OWASP Top 10 vulnerabilities.

## Input Validation

**Rule:** Validate all input at the trust boundary. Treat data from users, external APIs, files, and environment variables as untrusted until validated.

**Why:** Untrusted input is the source of most security vulnerabilities (injection, deserialization, path traversal).

**Good:**
```python
from pydantic import BaseModel, EmailStr, Field

class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    age: int = Field(ge=0, le=150)

def handle_request(raw_json: str) -> User:
    request = CreateUserRequest.model_validate_json(raw_json)
    return create_user(request)
```

**Bad:**
```python
def handle_request(raw_json: str) -> User:
    data = json.loads(raw_json)
    return create_user(data["email"], data["name"], data["age"])
    # no validation: any type, any size, any content accepted
```

## SQL Injection Prevention

**Rule:** Never build SQL queries by concatenating or formatting strings with user input. Use parameterized queries.

**Why:** String-built SQL is the textbook example of how databases get owned.

**Bad:**
```python
def fetch_user(email: str) -> User:
    query = f"SELECT * FROM users WHERE email = '{email}'"
    return db.execute(query).fetchone()
    # input "alice' OR '1'='1" returns all users
```

**Good:**
```python
def fetch_user(email: str) -> User:
    query = "SELECT * FROM users WHERE email = ?"
    return db.execute(query, (email,)).fetchone()
```

**Good (SQLAlchemy):**
```python
def fetch_user(email: str) -> User:
    return session.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()
```

## Command Injection Prevention

**Rule:** Never pass user input to a shell. Use `subprocess.run` with `shell=False` and a list of arguments.

**Why:** Shell expansion lets attackers chain commands.

**Bad:**
```python
import subprocess

def convert(filename: str) -> None:
    subprocess.run(f"convert {filename} output.png", shell=True)
    # filename = "input.png; rm -rf /" — game over
```

**Good:**
```python
import subprocess

def convert(filename: str) -> None:
    subprocess.run(
        ["convert", filename, "output.png"],
        shell=False,
        check=True,
    )
```

## Path Traversal Prevention

**Rule:** When user input determines a file path, resolve the path and verify it stays within an allowed root directory.

**Why:** Without validation, a user can read `../../../etc/passwd` or write into system directories.

**Bad:**
```python
def read_user_file(filename: str) -> str:
    with open(f"workspace/{filename}") as f:
        return f.read()
    # filename = "../../../etc/passwd"
```

**Good:**
```python
from pathlib import Path

WORKSPACE = Path("/app/workspace").resolve()

def read_user_file(filename: str) -> str:
    target = (WORKSPACE / filename).resolve()
    if not target.is_relative_to(WORKSPACE):
        raise PermissionError(f"Access denied: {filename}")
    with open(target) as f:
        return f.read()
```

## Avoid `eval`, `exec`, `pickle.loads` on Untrusted Data

**Rule:** Never call `eval`, `exec`, or `pickle.loads` on data from external sources.

**Why:** These functions execute arbitrary code embedded in the input. Pickle is particularly dangerous because it has no defensive mode.

**Bad:**
```python
import pickle

def load_session(session_data: bytes) -> Session:
    return pickle.loads(session_data)  # remote code execution
```

**Good:**
```python
import json

def load_session(session_data: str) -> Session:
    raw = json.loads(session_data)
    return Session.model_validate(raw)
```

## Secrets Management

**Rule:** Never hardcode secrets in source code. Load them from environment variables or a secret manager. Add `.env` files to `.gitignore`.

**Why:** Secrets in source code end up in version control history, container images, and logs. Rotation becomes impossible.

**Bad:**
```python
API_KEY = "sk-1234567890abcdef"
DB_PASSWORD = "admin123"
JWT_SECRET = "supersecret"
```

**Good:**
```python
import os

API_KEY = os.environ["API_KEY"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
JWT_SECRET = os.environ["JWT_SECRET"]

# fail at startup if not set, instead of mysterious runtime errors
```

**Good (with python-dotenv):**
```python
from dotenv import load_dotenv
load_dotenv()  # only in dev; production uses real env vars

API_KEY = os.environ["API_KEY"]
```

## Cryptographic Randomness

**Rule:** For tokens, IDs, passwords, or any value where unpredictability matters for security, use the `secrets` module, not `random`.

**Why:** `random` is seeded predictably and is not cryptographically secure. An attacker who sees enough output can predict future values.

**Bad:**
```python
import random
token = "".join(random.choices(string.ascii_letters + string.digits, k=32))
```

**Good:**
```python
import secrets
token = secrets.token_urlsafe(32)
# or: secrets.token_hex(32), secrets.choice(alphabet)
```

## Password Hashing

**Rule:** Never store passwords in plain text or with simple hashes like MD5 or SHA-1. Use `argon2` (preferred) or `bcrypt`.

**Why:** Modern password hashing algorithms are slow on purpose to resist brute-force attacks.

**Good:**
```python
from argon2 import PasswordHasher

ph = PasswordHasher()

def hash_password(password: str) -> str:
    return ph.hash(password)

def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return ph.verify(stored_hash, password)
    except VerifyMismatchError:
        return False
```

**Bad:**
```python
import hashlib
def hash_password(password: str) -> str:
    return hashlib.md5(password.encode()).hexdigest()  # broken
```

## HTTPS and Certificate Verification

**Rule:** All outbound HTTPS calls must verify TLS certificates. Never set `verify=False` except for local development with self-signed certs (and even then, only in non-production code).

**Why:** Disabling verification removes defense against man-in-the-middle attacks.

**Bad:**
```python
import httpx
response = httpx.get("https://api.example.com/data", verify=False)
```

**Good:**
```python
import httpx
response = httpx.get("https://api.example.com/data")  # verify=True by default
```

## HTTP Timeouts

**Rule:** Every outbound HTTP call must specify a timeout. Default Python HTTP libraries wait forever.

**Why:** Missing timeouts let a slow server hang your application indefinitely, an availability vulnerability.

**Bad:**
```python
response = httpx.get(url)  # no timeout
```

**Good:**
```python
response = httpx.get(url, timeout=10.0)

# or with finer control:
response = httpx.get(url, timeout=httpx.Timeout(30.0, connect=5.0))
```

## Cross-Site Scripting (XSS) Prevention

**Rule:** When rendering user content into HTML, escape it. Use template engines with auto-escaping enabled (Jinja2, Django templates).

**Why:** Raw user content in HTML lets attackers run JavaScript in other users' browsers.

**Bad (manual HTML):**
```python
def render_comment(comment: str) -> str:
    return f"<div>{comment}</div>"
    # comment = "<script>steal_cookies()</script>" — XSS
```

**Good:**
```python
from markupsafe import escape

def render_comment(comment: str) -> str:
    return f"<div>{escape(comment)}</div>"
```

## Cross-Site Request Forgery (CSRF) Protection

**Rule:** State-changing endpoints (POST, PUT, DELETE) must require a CSRF token or use SameSite cookies.

**Why:** Without CSRF protection, an attacker's site can trigger actions on behalf of a logged-in user.

**Good (FastAPI with Starlette):**
```python
from starlette.middleware.sessions import SessionMiddleware

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET,
    same_site="strict",
)
```

## Rate Limiting

**Rule:** Endpoints that perform expensive operations or accept authentication must be rate-limited.

**Why:** Without rate limiting, attackers can brute-force credentials, exhaust resources, or scrape data.

**Good (slowapi for FastAPI):**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, credentials: LoginRequest):
    ...
```

## Sandboxing Agent-Generated Code

**Rule:** Code generated by LLM agents must not be executed in a privileged environment. Use one of:
- Docker container with restricted capabilities
- Restricted Python interpreter (RestrictedPython)
- Subprocess in an isolated user account
- Cloud sandbox (Modal, E2B)

**Why:** Generated code may contain bugs, intentionally malicious patterns, or shell escapes.

**Good (Docker sandbox):**
```python
import subprocess

def run_user_code(code: str) -> str:
    return subprocess.run(
        [
            "docker", "run", "--rm",
            "--network=none",
            "--memory=128m",
            "--cpus=0.5",
            "--read-only",
            "--cap-drop=ALL",
            "python:3.11-slim",
            "python", "-c", code,
        ],
        capture_output=True, text=True, timeout=30,
    ).stdout
```

**Bad:**
```python
def run_user_code(code: str) -> str:
    exec(code)  # full access to your application
```

## Logging Sensitive Data

**Rule:** Never log passwords, API keys, tokens, full credit card numbers, or full personal identifiers.

**Why:** Logs end up in many places (files, log aggregators, support tickets). Sensitive data in logs is leaked data.

**Bad:**
```python
logger.info(f"User login: {email} with password {password}")
logger.info(f"Auth request: {request.headers}")  # leaks Authorization header
```

**Good:**
```python
logger.info(f"User login: {email}")  # email is fine; password is not

def safe_headers(headers: dict) -> dict:
    redacted = {"authorization", "cookie", "x-api-key"}
    return {k: ("***" if k.lower() in redacted else v) for k, v in headers.items()}

logger.info(f"Auth request: {safe_headers(request.headers)}")
```

## Dependency Vulnerabilities

**Rule:** Run vulnerability scans on dependencies. Resolve high-severity findings before merge.

**Why:** Most security incidents stem from outdated vulnerable dependencies, not custom code bugs.

**Tools:**
- `pip-audit` — Python advisory database
- `safety` — alternative scanner
- GitHub Dependabot (free for public repos)
- `npm audit` for any JS components

```bash
pip install pip-audit
pip-audit
```

## CORS Configuration

**Rule:** Set CORS origins explicitly to a known allow-list. Never use `allow_origins=["*"]` in production.

**Why:** `*` lets any origin make authenticated requests to your API.

**Bad:**
```python
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)
```

**Good:**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.example.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
```
