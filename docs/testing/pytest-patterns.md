# Pytest Patterns

This document defines testing conventions for code produced by the system. The QA agent uses these patterns when writing test cases.

## Test File Layout

**Rule:** Tests live in a top-level `tests/` directory that mirrors the source tree.

```
src/
├── agents/
│   ├── developer.py
│   └── reviewer.py
└── llm/
    └── pool.py

tests/
├── agents/
│   ├── test_developer.py
│   └── test_reviewer.py
└── llm/
    └── test_pool.py
```

**Why:** Mirrored structure makes it trivial to find the test for any file.

## Test File and Function Naming

**Rule:** Test files are named `test_<module>.py`. Test functions are named `test_<behavior_being_tested>`.

**Why:** pytest auto-discovers files starting with `test_` and functions starting with `test_`.

**Good:**
```python
# tests/llm/test_pool.py

def test_pick_node_returns_healthy_coder_for_coder_capability():
    ...

def test_pick_node_falls_back_when_capability_unavailable():
    ...

def test_pick_node_raises_when_all_nodes_unhealthy():
    ...
```

**Bad:**
```python
def test_pool():       # too vague
    ...

def test1():           # meaningless
    ...

def check_pool_pick():  # doesn't start with test_, won't run
    ...
```

## Arrange-Act-Assert Pattern

**Rule:** Every test must have three distinct sections, separated by blank lines or comments:
1. **Arrange:** set up inputs and state
2. **Act:** invoke the function under test
3. **Assert:** verify the outcome

**Why:** This structure makes tests instantly readable. A reader sees the setup, the action, and the check without parsing.

**Good:**
```python
def test_calculate_total_sums_item_prices():
    # Arrange
    items = [
        Item(name="apple", price=1.50),
        Item(name="bread", price=3.00),
        Item(name="milk", price=2.25),
    ]

    # Act
    total = calculate_total(items)

    # Assert
    assert total == 6.75
```

## One Assert Per Test (Soft Rule)

**Rule:** Prefer one logical assertion per test. Multiple `assert` statements that check facets of the same outcome are fine; assertions checking distinct behaviors should be separate tests.

**Why:** A test failure should pinpoint exactly which behavior broke.

**Good:**
```python
def test_create_user_assigns_id_and_email():
    user = create_user("alice@example.com")

    assert user.id is not None
    assert user.email == "alice@example.com"
    # all asserting one logical thing: "user is created with correct fields"


def test_create_user_logs_creation_event():
    with capture_logs() as logs:
        create_user("alice@example.com")
    assert "user_created" in [log.event for log in logs]
    # separate behavior, separate test
```

## Parametrize for Multiple Inputs

**Rule:** Use `@pytest.mark.parametrize` to test the same behavior across multiple inputs.

**Why:** Parametrization eliminates copy-paste and gives each case its own pass/fail status.

**Good:**
```python
import pytest

@pytest.mark.parametrize(
    "email,expected",
    [
        ("alice@example.com", True),
        ("bob@sub.example.co", True),
        ("invalid", False),
        ("@example.com", False),
        ("alice@", False),
        ("", False),
    ],
)
def test_is_valid_email(email, expected):
    assert is_valid_email(email) is expected
```

**Bad:**
```python
def test_valid_emails():
    assert is_valid_email("alice@example.com")
    assert is_valid_email("bob@sub.example.co")

def test_invalid_emails():
    assert not is_valid_email("invalid")
    assert not is_valid_email("@example.com")
    # one failure stops the test; can't see all failures at once
```

## Fixtures for Shared Setup

**Rule:** Use `@pytest.fixture` for setup that multiple tests share.

**Why:** Fixtures are reusable, composable, and have well-defined teardown.

**Good:**
```python
import pytest

@pytest.fixture
def healthy_pool():
    nodes = [
        LLMNode("pc1", "http://pc1:11434", "qwen", Capability.CODER),
        LLMNode("pc2", "http://pc2:11434", "llama", Capability.REASONER),
    ]
    return LLMPool(nodes=nodes)


def test_pool_picks_coder_for_coder_capability(healthy_pool):
    node = healthy_pool.pick_node(Capability.CODER)
    assert node.name == "pc1"


def test_pool_picks_reasoner_for_reasoner_capability(healthy_pool):
    node = healthy_pool.pick_node(Capability.REASONER)
    assert node.name == "pc2"
```

## Fixture Scopes

**Rule:** Default to function-scoped fixtures (`scope="function"`). Use `module` or `session` scope only for expensive setup that is provably safe to share.

**Why:** Function scope guarantees test isolation. Wider scopes risk cross-test contamination.

**Good:**
```python
@pytest.fixture(scope="session")
def temp_chroma_db(tmp_path_factory):
    """Expensive: spin up ChromaDB once for the whole test session."""
    path = tmp_path_factory.mktemp("chroma")
    db = chromadb.PersistentClient(path=str(path))
    yield db
    # teardown: nothing needed
```

## Mocking External Dependencies

**Rule:** Mock at the boundary of your unit, not internal to it. Use `unittest.mock` or `pytest-mock`.

**Why:** Mocking internal calls couples your tests to implementation. Mocking the boundary (HTTP, DB, filesystem) keeps tests fast and stable.

**Good:**
```python
from unittest.mock import AsyncMock

async def test_pool_uses_fallback_when_primary_fails(mocker):
    pool = LLMPool(nodes=[...])
    mock_client = mocker.patch.object(pool, "client")
    mock_client.post = AsyncMock(side_effect=[
        httpx.ConnectError("pc1 down"),
        Response(200, json={"response": "fallback ok"}),
    ])

    result = await pool.generate("hello", capability=Capability.CODER)

    assert result == "fallback ok"
    assert mock_client.post.call_count == 2
```

**Bad:**
```python
def test_pool_internal_method(mocker):
    pool = LLMPool(...)
    mocker.patch.object(pool, "_select_candidates")  # mocking internals
    pool.pick_node(Capability.CODER)
```

## Test Edge Cases

**Rule:** Every function must be tested with at least:
- The happy path (typical input)
- Empty input (`[]`, `""`, `None` if applicable)
- Boundary values (0, max size, max length)
- Invalid input that should raise

**Why:** Most bugs hide at edges. The middle of the input space is usually correct.

**Good:**
```python
@pytest.mark.parametrize(
    "items,expected",
    [
        ([1, 2, 3], 6),       # happy path
        ([], 0),              # empty
        ([0], 0),             # boundary
        ([-1, -2, -3], -6),   # negatives
        ([10**9, 10**9], 2 * 10**9),  # large values
    ],
)
def test_sum_items(items, expected):
    assert sum_items(items) == expected


def test_sum_items_raises_on_non_numeric():
    with pytest.raises(TypeError):
        sum_items(["a", "b"])
```

## Testing for Exceptions

**Rule:** Use `pytest.raises` as a context manager to assert that code raises the expected exception. Optionally check the exception message with `match=`.

**Why:** `pytest.raises` confirms the exception type and lets you inspect the exception instance.

**Good:**
```python
def test_divide_by_zero_raises():
    with pytest.raises(ZeroDivisionError, match="Cannot divide by zero"):
        divide(10, 0)


def test_fetch_unknown_user_raises():
    with pytest.raises(UserNotFoundError) as exc_info:
        fetch_user(user_id=999999)
    assert exc_info.value.user_id == 999999
```

**Bad:**
```python
def test_divide_by_zero_raises():
    try:
        divide(10, 0)
        assert False, "should have raised"
    except ZeroDivisionError:
        pass
```

## Async Tests

**Rule:** Async tests require `pytest-asyncio`. Mark tests with `@pytest.mark.asyncio` or set `asyncio_mode = "auto"` in config.

**Good:**
```python
import pytest

@pytest.mark.asyncio
async def test_pool_generates_response():
    pool = LLMPool(nodes=[...])
    response = await pool.generate("test", capability=Capability.CODER)
    assert response.strip() != ""
```

## Test Independence

**Rule:** Tests must not depend on order or shared mutable state.

**Why:** Order-dependent tests pass locally and fail in CI. They are nightmares to debug.

**Good:**
```python
@pytest.fixture
def empty_cache():
    return Cache()  # fresh instance per test


def test_cache_set_and_get(empty_cache):
    empty_cache.set("key", "value")
    assert empty_cache.get("key") == "value"


def test_cache_returns_none_for_missing_key(empty_cache):
    assert empty_cache.get("missing") is None
```

**Bad:**
```python
cache = Cache()  # module-level, shared


def test_cache_set():
    cache.set("key", "value")


def test_cache_get():  # depends on test_cache_set having run first
    assert cache.get("key") == "value"
```

## Coverage Targets

**Rule:** Aim for >80% line coverage on production code. The goal is not the number; it is having tests that exercise meaningful behavior.

**Why:** Coverage measures execution, not correctness. 100% coverage of trivial tests is worse than 70% coverage of meaningful ones.

**Run coverage:**
```bash
pytest --cov=src --cov-report=term-missing --cov-report=html
```

## Running Tests

```bash
# Run all tests
pytest

# Run a specific file
pytest tests/llm/test_pool.py

# Run a specific test
pytest tests/llm/test_pool.py::test_pool_picks_coder_for_coder_capability

# Verbose output
pytest -v

# Stop at first failure
pytest -x

# Run with coverage
pytest --cov=src

# Run only tests matching a keyword
pytest -k "pool and coder"
```
