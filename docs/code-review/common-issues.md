# Common Code Issues

This document catalogs frequently-occurring bugs and anti-patterns that reviewer agents should be especially vigilant about. Each issue includes the symptom, the cause, and the fix.

## Mutable Default Arguments

**Symptom:** A list or dict default argument retains values across function calls.

**Cause:** Python evaluates default arguments once at function definition. Mutating the default mutates the shared object.

**Bad:**
```python
def append_log(entry, log=[]):
    log.append(entry)
    return log

a = append_log("start")  # ["start"]
b = append_log("step")   # ["start", "step"]  — shared!
```

**Good:**
```python
def append_log(entry, log=None):
    if log is None:
        log = []
    log.append(entry)
    return log
```

## Late Binding in Closures

**Symptom:** Functions created in a loop all use the final value of the loop variable.

**Cause:** Closures capture variables by reference, not by value. When the closure runs later, it reads the current (final) value.

**Bad:**
```python
funcs = [lambda: i for i in range(3)]
[f() for f in funcs]  # [2, 2, 2], not [0, 1, 2]
```

**Good:**
```python
funcs = [lambda i=i: i for i in range(3)]  # bind i at definition
[f() for f in funcs]  # [0, 1, 2]
```

## Off-by-One Errors

**Symptom:** Loop processes one item too many or too few.

**Cause:** Confusion between inclusive and exclusive ranges, or between length and index.

**Bad:**
```python
for i in range(len(items) - 1):  # misses last item
    process(items[i])

for i in range(1, len(items)):  # misses first item
    process(items[i])
```

**Good:**
```python
for item in items:
    process(item)

for i, item in enumerate(items):
    process(i, item)
```

## Catching Too Broad an Exception

**Symptom:** Bug reports show a generic error message; the real exception is hidden.

**Cause:** `except Exception` or `except:` swallows unrelated errors, including bugs.

**Bad:**
```python
try:
    user = fetch_user(user_id)
except Exception:
    user = None  # masks ANY error: network, parse, bug, KeyboardInterrupt
```

**Good:**
```python
try:
    user = fetch_user(user_id)
except UserNotFoundError:
    user = None
except DatabaseError:
    logger.exception("Database unavailable")
    raise
```

## Comparing with `==` to None

**Symptom:** Works most of the time but breaks with custom `__eq__` implementations.

**Cause:** `==` invokes `__eq__`, which can be overridden. `is` checks object identity.

**Bad:**
```python
if user == None:
    raise ValueError
```

**Good:**
```python
if user is None:
    raise ValueError
```

## Modifying a Collection While Iterating

**Symptom:** `RuntimeError: dictionary changed size during iteration` or skipped/duplicated items.

**Cause:** Mutating a collection invalidates the iterator's state.

**Bad:**
```python
for key in cache:
    if is_expired(cache[key]):
        del cache[key]  # raises RuntimeError
```

**Good:**
```python
expired = [key for key, value in cache.items() if is_expired(value)]
for key in expired:
    del cache[key]
```

## String Concatenation in Loops

**Symptom:** Quadratic time complexity when building strings.

**Cause:** Strings are immutable. Each `+=` creates a new string and copies the old one.

**Bad:**
```python
result = ""
for chunk in chunks:
    result += chunk  # O(n²)
```

**Good:**
```python
result = "".join(chunks)
```

## N+1 Query Pattern

**Symptom:** Loading a list with related objects takes many small queries instead of one big one.

**Cause:** Looping over results and triggering a query for each row.

**Bad:**
```python
users = User.query.all()
for user in users:
    print(user.profile.bio)  # one query per user
```

**Good:**
```python
users = User.query.options(joinedload(User.profile)).all()
for user in users:
    print(user.profile.bio)  # single query
```

## Resource Leaks

**Symptom:** File descriptors exhausted, connections accumulating, files left open.

**Cause:** Not using context managers or `try/finally` to ensure cleanup.

**Bad:**
```python
f = open("data.txt")
data = f.read()
process(data)  # if this raises, file never closes
f.close()
```

**Good:**
```python
with open("data.txt") as f:
    data = f.read()
process(data)
```

## Race Conditions

**Symptom:** Inconsistent behavior under concurrent load. Counts come out wrong.

**Cause:** Non-atomic read-modify-write operations on shared state.

**Bad:**
```python
counter = 0
async def increment():
    global counter
    counter = counter + 1  # not atomic
```

**Good:**
```python
counter = 0
lock = asyncio.Lock()

async def increment():
    global counter
    async with lock:
        counter = counter + 1
```

## Silent Failures

**Symptom:** Errors disappear without log entries; bugs are hard to find.

**Cause:** Logging the exception but not its traceback, or using `pass` in an except block.

**Bad:**
```python
try:
    risky_call()
except Exception as e:
    logger.error(f"failed: {e}")  # no traceback
```

**Good:**
```python
try:
    risky_call()
except Exception:
    logger.exception("risky_call failed")  # includes traceback
    raise
```

## Hardcoded Secrets

**Symptom:** Credentials, API keys, or tokens visible in source code.

**Cause:** Convenience trumping security during development.

**Bad:**
```python
API_KEY = "sk-1234567890abcdef"
DB_PASSWORD = "admin123"
```

**Good:**
```python
import os
API_KEY = os.environ["API_KEY"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
```

## Using `==` for Float Comparison

**Symptom:** Floating-point equality checks fail unexpectedly.

**Cause:** `0.1 + 0.2 != 0.3` due to IEEE 754 representation.

**Bad:**
```python
if total == 0.3:
    ...
```

**Good:**
```python
import math
if math.isclose(total, 0.3, rel_tol=1e-9):
    ...
```

## Subprocess Shell Injection

**Symptom:** User input is interpreted as shell commands.

**Cause:** Using `shell=True` with string-formatted user input.

**Bad:**
```python
import subprocess
filename = request.json["filename"]
subprocess.run(f"cat {filename}", shell=True)
# user sends "x; rm -rf /" — game over
```

**Good:**
```python
import subprocess
filename = request.json["filename"]
subprocess.run(["cat", filename], shell=False)
```

## Blocking Calls in Async Code

**Symptom:** Async application freezes or has unexpectedly poor throughput.

**Cause:** Calling synchronous I/O or `time.sleep` inside `async def`.

**Bad:**
```python
async def fetch_all(urls):
    results = []
    for url in urls:
        results.append(requests.get(url))  # blocks event loop
    return results
```

**Good:**
```python
async def fetch_all(urls):
    async with httpx.AsyncClient() as client:
        return await asyncio.gather(*(client.get(url) for url in urls))
```

## Using `is` for Value Comparison

**Symptom:** Works for small integers and short strings due to interning, fails for others.

**Cause:** Confusing identity (`is`) with equality (`==`).

**Bad:**
```python
if status is "active":  # works by accident due to string interning
    ...

if count is 1000:  # fails: integer caching only -5..256
    ...
```

**Good:**
```python
if status == "active":
    ...

if count == 1000:
    ...
```

## Forgetting to Close HTTP Clients

**Symptom:** Connection pool exhaustion, "too many open files" errors.

**Cause:** Creating an `httpx.Client` or `requests.Session` and never closing it.

**Bad:**
```python
async def call_api():
    client = httpx.AsyncClient()  # leaks
    response = await client.get(URL)
    return response.json()
```

**Good (per-call):**
```python
async def call_api():
    async with httpx.AsyncClient() as client:
        response = await client.get(URL)
        return response.json()
```

**Good (singleton, app-scoped):**
```python
# at module level
client = httpx.AsyncClient()

async def call_api():
    response = await client.get(URL)
    return response.json()

# at app shutdown:
await client.aclose()
```
