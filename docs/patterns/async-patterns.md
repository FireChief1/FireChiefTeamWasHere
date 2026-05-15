# Async and Concurrency Patterns

This document defines patterns for asynchronous code in the project. The LLM pool, agent dispatch, and pipeline parallelism all depend on correct async usage.

## When to Use Async

**Rule:** Use `async` for I/O-bound work: HTTP calls, database queries, file I/O, subprocess communication. Do not use async for CPU-bound work.

**Why:** Async lets a single thread interleave many waiting operations. It does not speed up computation.

**Good:**
```python
async def fetch_all_users(user_ids: list[int]) -> list[User]:
    async with httpx.AsyncClient() as client:
        coros = [client.get(f"/users/{uid}") for uid in user_ids]
        responses = await asyncio.gather(*coros)
    return [User.model_validate(r.json()) for r in responses]
```

**Bad (CPU-bound, async adds no value):**
```python
async def calculate_factorial(n: int) -> int:
    if n <= 1:
        return 1
    return n * await calculate_factorial(n - 1)
```

## Async All the Way Down

**Rule:** If a function is async, every function it awaits must also be async. Don't mix sync I/O with async code.

**Why:** A sync call blocks the entire event loop, freezing every other concurrent task.

**Bad:**
```python
async def fetch_and_save(url: str) -> None:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    with open("output.txt", "w") as f:  # blocking
        f.write(response.text)
```

**Good:**
```python
import aiofiles

async def fetch_and_save(url: str) -> None:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    async with aiofiles.open("output.txt", "w") as f:
        await f.write(response.text)
```

**Good (if you must call sync code):**
```python
import asyncio

async def fetch_and_process(url: str) -> Result:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    result = await asyncio.to_thread(cpu_intensive_parse, response.content)
    return result
```

## Parallel Tasks with `asyncio.gather`

**Rule:** When multiple async tasks have no ordering dependency, run them in parallel with `asyncio.gather`.

**Why:** Sequential `await` of independent calls wastes time. `gather` runs them concurrently.

**Bad:**
```python
async def fetch_user_dashboard(user_id: int) -> Dashboard:
    user = await fetch_user(user_id)              # 100ms
    posts = await fetch_posts(user_id)            # 100ms
    notifications = await fetch_notifications(user_id)  # 100ms
    return Dashboard(user, posts, notifications)  # total: 300ms
```

**Good:**
```python
async def fetch_user_dashboard(user_id: int) -> Dashboard:
    user, posts, notifications = await asyncio.gather(
        fetch_user(user_id),
        fetch_posts(user_id),
        fetch_notifications(user_id),
    )
    return Dashboard(user, posts, notifications)  # total: ~100ms
```

## Error Handling with `gather`

**Rule:** Use `return_exceptions=True` when you want to handle some failures without aborting the whole batch.

**Why:** By default, `gather` re-raises the first exception and cancels remaining tasks. Sometimes you want all results regardless.

**Good (all-or-nothing):**
```python
results = await asyncio.gather(*coros)  # raises on first failure
```

**Good (best-effort):**
```python
results = await asyncio.gather(*coros, return_exceptions=True)
for result in results:
    if isinstance(result, Exception):
        logger.warning("task failed", error=result)
    else:
        process(result)
```

## Task Groups (Python 3.11+)

**Rule:** For tasks that share a lifetime and must be cleaned up together, use `asyncio.TaskGroup` instead of manual `gather`.

**Why:** TaskGroups guarantee that if any task fails, all sibling tasks are cancelled and the failure is surfaced.

**Good:**
```python
async def process_batch(items: list[Item]) -> list[Result]:
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(process(item)) for item in items]
    return [task.result() for task in tasks]
```

## Timeouts

**Rule:** Every external operation must have a timeout. Use `asyncio.wait_for` or `asyncio.timeout`.

**Why:** Without timeouts, a hung dependency hangs your service.

**Good (Python 3.11+):**
```python
async def fetch_with_timeout(url: str) -> str:
    async with asyncio.timeout(10):
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            return response.text
```

**Good (older Python):**
```python
async def fetch_with_timeout(url: str) -> str:
    try:
        return await asyncio.wait_for(fetch(url), timeout=10)
    except asyncio.TimeoutError:
        logger.warning(f"timeout fetching {url}")
        raise
```

## Cancellation

**Rule:** Async code must handle `asyncio.CancelledError` gracefully. Release resources, then re-raise.

**Why:** Cancellation is how async tasks are stopped. Suppressing it breaks the cancellation chain.

**Good:**
```python
async def stream_responses(url: str):
    client = httpx.AsyncClient()
    try:
        async for chunk in client.stream("GET", url):
            yield chunk
    except asyncio.CancelledError:
        logger.info(f"stream cancelled: {url}")
        raise
    finally:
        await client.aclose()
```

**Bad:**
```python
async def stream_responses(url: str):
    try:
        async for chunk in stream(url):
            yield chunk
    except Exception:
        pass  # swallows CancelledError too
```

## Locks for Shared State

**Rule:** When async tasks share mutable state, protect it with `asyncio.Lock`.

**Why:** Async tasks can preempt each other at any `await`. Read-modify-write sequences are not atomic.

**Bad:**
```python
counter = 0

async def increment():
    global counter
    current = counter        # await may switch here
    await asyncio.sleep(0)   # context switch point
    counter = current + 1    # writes stale value
```

**Good:**
```python
counter = 0
counter_lock = asyncio.Lock()

async def increment():
    global counter
    async with counter_lock:
        counter += 1
```

## Connection Pooling

**Rule:** HTTP clients must be reused, not created per request. Configure the connection pool size explicitly.

**Why:** Creating a new client per request wastes TCP handshakes and exhausts ephemeral ports.

**Good (module singleton):**
```python
# llm/clients.py
import httpx

_client: httpx.AsyncClient | None = None

def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=50,
                max_keepalive_connections=20,
                keepalive_expiry=60.0,
            ),
            timeout=httpx.Timeout(60.0, connect=5.0),
        )
    return _client

async def shutdown():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
```

## Backpressure with Semaphores

**Rule:** When dispatching many tasks at once, limit concurrency with `asyncio.Semaphore` to avoid overwhelming downstream services.

**Why:** Unbounded concurrency causes rate-limit hits, timeouts, and out-of-memory errors.

**Good:**
```python
async def fetch_many(urls: list[str], max_concurrent: int = 10) -> list[Response]:
    semaphore = asyncio.Semaphore(max_concurrent)

    async def bounded_fetch(url: str) -> Response:
        async with semaphore:
            return await fetch(url)

    return await asyncio.gather(*(bounded_fetch(u) for u in urls))
```

## Async Iteration

**Rule:** Use `async for` to consume async iterators. Implement `__aiter__` and `__anext__` for custom async iterators.

**Why:** Async iteration lets you yield control between items, useful for streaming results.

**Good:**
```python
async def stream_llm_response(prompt: str):
    async with httpx.AsyncClient() as client:
        async with client.stream("POST", URL, json={"prompt": prompt}) as response:
            async for line in response.aiter_lines():
                yield json.loads(line)


async def main():
    async for token in stream_llm_response("Hello"):
        print(token, end="", flush=True)
```

## Pipeline Parallelism with `abatch`

**Rule:** When invoking the same workflow on multiple inputs, use the framework's batch method (e.g., LangGraph's `abatch`) instead of a manual loop.

**Why:** Batch invocation is naturally parallel and respects per-node concurrency limits.

**Good:**
```python
results = await workflow.abatch(
    inputs=[
        {"task": "Implement fibonacci"},
        {"task": "Fix auth bug"},
        {"task": "Add input validation"},
    ],
    config={"max_concurrency": 3},
)
```

## Common Async Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Forgetting `await` | Coroutine warning, function returns coroutine object | Add `await` |
| Calling sync I/O in async | Event loop freezes, throughput drops | Use async equivalent or `asyncio.to_thread` |
| `time.sleep` in async | Event loop blocks | Use `asyncio.sleep` |
| Not awaiting fire-and-forget tasks | Task gets garbage-collected mid-execution | Keep reference: `task = asyncio.create_task(...)` |
| Using `asyncio.run` inside an async function | RuntimeError: cannot run event loop | Just `await` the coroutine |
| Race conditions on shared state | Inconsistent values | Use `asyncio.Lock` |

## Testing Async Code

```python
import pytest

@pytest.mark.asyncio
async def test_pool_concurrent_calls():
    pool = LLMPool(...)
    results = await asyncio.gather(
        pool.generate("task A", Capability.CODER),
        pool.generate("task B", Capability.REASONER),
    )
    assert len(results) == 2
```

Configure `pytest-asyncio` in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```
