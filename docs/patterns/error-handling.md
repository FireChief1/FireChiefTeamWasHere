# Error Handling Patterns

This document defines how the project handles errors. Robust error handling is the difference between a system that recovers gracefully and one that silently corrupts state.

## Use Specific Exceptions

**Rule:** Catch specific exception types, not `Exception` or bare `except`.

**Why:** Broad excepts swallow unrelated errors, including bugs in your own code and `KeyboardInterrupt` from users.

**Good:**
```python
try:
    response = await client.post(url, json=payload)
    response.raise_for_status()
except httpx.TimeoutException:
    logger.warning(f"timeout calling {url}")
    raise
except httpx.HTTPStatusError as e:
    logger.error(f"http error {e.response.status_code}")
    raise
```

**Bad:**
```python
try:
    response = await client.post(url, json=payload)
    response.raise_for_status()
except Exception as e:
    logger.error(f"call failed: {e}")
    return None  # masks all errors including bugs
```

## Custom Exception Hierarchy

**Rule:** Define a project base exception. Subclass it for each error category. Library/framework exceptions should propagate up or be wrapped in your own.

**Why:** Custom exceptions let callers handle different failure modes precisely. A hierarchy lets them catch broadly when desired.

**Good:**
```python
class AppError(Exception):
    """Base exception for the application."""


class LLMError(AppError):
    """LLM-related failures."""


class LLMTimeoutError(LLMError):
    """LLM call exceeded the configured timeout."""


class LLMRateLimitError(LLMError):
    """LLM provider rate-limited the request."""


class AgentError(AppError):
    """Agent execution failures."""


class AgentParseError(AgentError):
    """Agent output could not be parsed."""


# usage:
try:
    result = await agent.run(task)
except AgentParseError:
    return await fallback_agent.run(task)
except LLMTimeoutError:
    return cached_response()
except AppError:
    logger.exception("app-level failure")
    raise
```

## Fail Fast on Programmer Errors

**Rule:** When invariants are violated (impossible state, bad arguments), raise immediately. Do not return error codes or silently coerce.

**Why:** Bugs that crash loudly are easy to find. Bugs that limp along corrupt data.

**Good:**
```python
def compute_discount(price: Decimal, percentage: Decimal) -> Decimal:
    if percentage < 0 or percentage > 1:
        raise ValueError(f"percentage must be in [0, 1], got {percentage}")
    return price * (1 - percentage)
```

**Bad:**
```python
def compute_discount(price: Decimal, percentage: Decimal) -> Decimal:
    if percentage < 0:
        percentage = 0  # silently fixes input
    elif percentage > 1:
        percentage = 1
    return price * (1 - percentage)
```

## Include Context in Error Messages

**Rule:** Exception messages must include enough context to debug from a log line alone.

**Why:** Production logs are often the only evidence of a bug. A naked "not found" is useless; "user 42 not found in database 'primary'" is actionable.

**Good:**
```python
raise UserNotFoundError(
    f"User not found: user_id={user_id}, database={db_name}, "
    f"queried_at={datetime.utcnow().isoformat()}"
)
```

**Bad:**
```python
raise UserNotFoundError("not found")
```

## Re-raise with `raise` (No Reassignment)

**Rule:** When catching to add context or logging, re-raise with bare `raise`. Use `raise NewError(...) from e` when wrapping.

**Why:** Bare `raise` preserves the original traceback. `from e` keeps the cause visible. Reassigning to `raise e` loses the traceback line.

**Good (logging then re-raise):**
```python
try:
    process(item)
except ProcessingError:
    logger.exception("processing failed for item %s", item.id)
    raise
```

**Good (wrapping):**
```python
try:
    response = httpx.get(url)
except httpx.RequestError as e:
    raise LLMConnectionError(f"could not reach LLM at {url}") from e
```

**Bad:**
```python
try:
    process(item)
except ProcessingError as e:
    logger.error(str(e))
    raise e  # discards traceback frames
```

## Use Context Managers for Cleanup

**Rule:** Resources that must be released (files, connections, locks) belong in `with` blocks. For custom resources, implement `__enter__`/`__exit__` or use `contextlib.contextmanager`.

**Why:** Context managers guarantee cleanup even on exceptions. `try/finally` works but is more verbose.

**Good:**
```python
from contextlib import contextmanager

@contextmanager
def acquire_lock(name: str):
    lock = obtain_lock(name)
    try:
        yield lock
    finally:
        lock.release()


with acquire_lock("user_table"):
    update_users()
```

**Bad:**
```python
lock = obtain_lock("user_table")
update_users()
lock.release()  # if update_users raises, lock leaks
```

## `try/except/else/finally` Structure

**Rule:** Put the smallest possible block in `try`. Use `else` for code that runs only on success. Use `finally` for unconditional cleanup.

**Why:** Minimal `try` blocks catch only the exceptions you intend. `else` clarifies the success path.

**Good:**
```python
try:
    response = await fetch(url)
except httpx.HTTPError:
    logger.warning("fetch failed")
    raise
else:
    # only runs if fetch succeeded
    parsed = parse(response)
    store(parsed)
finally:
    record_attempt()
```

## Retry with Exponential Backoff

**Rule:** Transient failures (network, rate limits, temporary unavailability) should be retried with exponential backoff and jitter. Use `tenacity` library.

**Why:** Constant-interval retries can DOS the recovering service. Exponential backoff gives it room to recover.

**Good:**
```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    reraise=True,
)
async def fetch_with_retry(url: str) -> Response:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response
```

## Do NOT Retry Programmer Errors

**Rule:** Retry only transient errors (network, rate limit, 5xx, timeouts). Do not retry on `ValueError`, `KeyError`, `TypeError`, 4xx client errors.

**Why:** Bugs don't fix themselves on retry. Retrying a 404 wastes resources and amplifies bugs.

**Good:**
```python
@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
)
async def call_api(): ...
```

**Bad:**
```python
@retry(stop=stop_after_attempt(5))  # retries on EVERYTHING
async def call_api(): ...
```

## Circuit Breaker Pattern

**Rule:** When a downstream service is failing, stop sending requests for a cooldown period instead of hammering it.

**Why:** Continued requests during outages overload the recovering service and waste local resources.

**Good (using `purgatory`):**
```python
from purgatory import CircuitBreaker

breaker = CircuitBreaker(threshold=5, ttl=30)

@breaker
async def call_external_api():
    async with httpx.AsyncClient(timeout=5) as client:
        return await client.get("https://api.example.com/data")
```

## Logging Exceptions

**Rule:** Use `logger.exception` inside an `except` block. It logs the message plus the full traceback automatically.

**Why:** A stack trace is the most valuable artifact when diagnosing an error.

**Good:**
```python
try:
    process(item)
except ProcessingError:
    logger.exception("failed to process item %s", item.id)
    raise
```

**Bad:**
```python
try:
    process(item)
except ProcessingError as e:
    logger.error(f"failed: {e}")  # loses traceback
```

## Avoid Returning `None` on Error

**Rule:** Prefer raising exceptions for error conditions. Return `None` only when "not found" or "absent" is a normal, expected outcome.

**Why:** `None` returns force every caller to check, and callers forget. Exceptions cannot be ignored silently.

**Good (exception for error):**
```python
def fetch_user(user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(f"user_id={user_id}")
    return user
```

**Good (None for absent):**
```python
def find_user_by_email(email: str) -> User | None:
    """Returns the user if found, otherwise None.

    None is a normal outcome here, not an error.
    """
    return db.query(User).filter_by(email=email).first()
```

**Bad (None for error):**
```python
def fetch_user(user_id: int) -> User | None:
    try:
        return db.get(User, user_id)
    except Exception:
        return None  # callers must check, will forget
```

## Cleanup with `finally`

**Rule:** Use `finally` for cleanup that must happen regardless of success or failure.

**Why:** Without `finally`, exceptions skip cleanup code, leaking resources.

**Good:**
```python
def write_atomic(path: Path, content: str) -> None:
    temp = path.with_suffix(".tmp")
    try:
        temp.write_text(content)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)
```

## Validation Errors

**Rule:** Input validation errors must clearly identify which field failed and why. Pydantic errors do this automatically; manual validation should match.

**Good:**
```python
from pydantic import BaseModel, ValidationError

class UserCreateRequest(BaseModel):
    email: EmailStr
    age: int = Field(ge=0, le=150)

try:
    request = UserCreateRequest.model_validate(payload)
except ValidationError as e:
    return JSONResponse(status_code=422, content=e.errors())
```

## Don't Use Exceptions for Flow Control

**Rule:** Exceptions are for exceptional conditions. Don't use `try/except` to handle normal program flow.

**Why:** Raising exceptions is slow and obscures intent.

**Bad:**
```python
def has_key(d: dict, key: str) -> bool:
    try:
        d[key]
        return True
    except KeyError:
        return False
```

**Good:**
```python
def has_key(d: dict, key: str) -> bool:
    return key in d
```
