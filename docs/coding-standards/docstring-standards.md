# Docstring Standards

This project uses **Google-style docstrings** for all public modules, classes, functions, and methods. Docstrings are how the system communicates intent to humans and to other LLM agents reading the code.

## When Docstrings Are Required

**Rule:** Docstrings are required for:
- Every public module
- Every public class
- Every public function and method
- Every function or method that raises an exception not implied by its signature

Private members (prefixed `_`) and trivial getters/setters do not require docstrings unless behavior is non-obvious.

**Why:** Public APIs are contracts. Documenting them lets consumers use the API without reading the implementation.

## Format: Google Style

**Rule:** Use Google-style docstrings with these sections (in order):
1. Summary line (one sentence, imperative mood, ends with period)
2. Optional extended description (blank line then paragraph)
3. `Args:` — parameter descriptions
4. `Returns:` — return value description
5. `Raises:` — exceptions raised
6. `Examples:` — optional usage examples

**Why:** Google style is concise, readable in source, and supported by all major doc generators (Sphinx, MkDocs).

**Good:**
```python
def fetch_user(user_id: int, *, include_deleted: bool = False) -> User:
    """Fetch a user by ID from the primary database.

    Performs a single indexed lookup. Deleted users are excluded by default.

    Args:
        user_id: The unique identifier of the user to fetch.
        include_deleted: If True, soft-deleted users are also returned.

    Returns:
        The User object matching the given ID.

    Raises:
        UserNotFoundError: If no user matches the given ID.
        DatabaseConnectionError: If the database is unreachable.

    Examples:
        >>> user = fetch_user(42)
        >>> user.email
        'alice@example.com'
    """
```

## Summary Line

**Rule:** The first line is a single-sentence summary in imperative mood (like a command).

**Why:** Imperative mood ("Fetch a user...") is shorter and reads better than third person ("This function fetches a user..."). It also matches how git commit messages and most API docs are written.

**Good:**
```python
def parse_response(raw: bytes) -> dict:
    """Parse a JSON response body into a Python dictionary."""
```

**Bad:**
```python
def parse_response(raw: bytes) -> dict:
    """This function parses the JSON response."""

def parse_response(raw: bytes) -> dict:
    """Parses a JSON response."""  # not imperative
```

## Args Section

**Rule:** Document every parameter. Use the format `param_name: description.`

Each description starts with a capital letter and ends with a period. If type information is conveyed by the type hint, do not repeat it in the docstring.

**Why:** Type hints provide the types; the docstring explains semantics.

**Good:**
```python
def send_email(recipient: str, subject: str, body: str, *, attachments: list[Path] | None = None) -> bool:
    """Send an email to the given recipient.

    Args:
        recipient: The email address to send to. Must be a valid RFC 5322 address.
        subject: The subject line. Truncated to 78 characters if longer.
        body: The plain-text body of the email.
        attachments: Optional list of file paths to attach. Files are read at send time.

    Returns:
        True if the email was queued successfully, False otherwise.
    """
```

**Bad:**
```python
def send_email(recipient: str, subject: str, body: str, *, attachments: list[Path] | None = None) -> bool:
    """Send an email.

    Args:
        recipient (str): the recipient.   # repeats type, lowercase, no period
        subject: subject
        body (str): body
    """
```

## Returns Section

**Rule:** Always document the return value unless the function returns `None`. If returning `None` is meaningful (not just "nothing to return"), document that too.

**Why:** Callers need to know what they will receive, including possible `None` returns or sentinel values.

**Good:**
```python
def find_user_by_email(email: str) -> User | None:
    """Find a user by their email address.

    Args:
        email: The email address to search for.

    Returns:
        The matching User if found, otherwise None.
    """
```

## Raises Section

**Rule:** Document every exception that the function may raise (excluding built-in exceptions that are obvious from the type hints, like `TypeError` on wrong-type input).

**Why:** Exception contracts are part of the public API. Undocumented exceptions cause production incidents.

**Good:**
```python
def divide(numerator: float, denominator: float) -> float:
    """Divide numerator by denominator.

    Args:
        numerator: The dividend.
        denominator: The divisor.

    Returns:
        The result of numerator / denominator.

    Raises:
        ZeroDivisionError: If denominator is zero.
    """
    if denominator == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return numerator / denominator
```

## Examples Section

**Rule:** Include `Examples:` for non-trivial functions. Use doctest format with `>>>`. Keep examples runnable and self-contained.

**Why:** Examples are the fastest way for a reader to understand usage. They also serve as executable documentation when run with `pytest --doctest-modules`.

**Good:**
```python
def chunk(items: list, size: int) -> list[list]:
    """Split a list into chunks of the given size.

    Args:
        items: The list to split.
        size: The maximum size of each chunk.

    Returns:
        A list of chunks, where each chunk has at most `size` elements.

    Examples:
        >>> chunk([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
        >>> chunk([], 3)
        []
    """
```

## Module Docstrings

**Rule:** Every module must start with a one-paragraph docstring describing its purpose.

**Why:** When opening a file, the first thing the reader (or LLM agent) sees should explain what the file is for.

**Good:**
```python
"""HTTP client utilities for the LLM backend pool.

This module provides a singleton AsyncClient instance configured with
connection pooling, retry policies, and circuit breaker integration.
All outbound HTTP calls to LLM backends must go through this client.
"""

import httpx
from tenacity import retry
...
```

## Class Docstrings

**Rule:** Class docstrings describe the class's purpose and key attributes. Document `__init__` arguments in the class docstring's `Args:` section, not in `__init__`'s docstring (unless `__init__` does complex work worth describing separately).

**Why:** Class docstrings are what `help(MyClass)` shows. Putting init params there keeps them discoverable.

**Good:**
```python
class LLMPool:
    """A capability-aware pool of LLM backend nodes.

    Routes requests to healthy nodes based on the requested capability
    (e.g., coding, reasoning, fallback). Implements connection pooling,
    health checks, and circuit breaker for fault tolerance.

    Attributes:
        nodes: The list of registered LLMNode instances.
        client: The shared httpx AsyncClient instance.

    Args:
        nodes: Initial list of LLMNode instances to register.
        health_check_interval: Seconds between health probes. Default 15.
    """

    def __init__(self, nodes: list[LLMNode], *, health_check_interval: int = 15):
        self.nodes = nodes
        ...
```

## Don't Document the Obvious

**Rule:** Do not write docstrings that just restate the function name or type signature.

**Why:** Empty docstrings add noise without value. Either explain something useful or omit the docstring on private helpers.

**Good:**
```python
def calculate_compound_interest(principal: Decimal, rate: float, years: int) -> Decimal:
    """Calculate compound interest using monthly compounding.

    Returns principal * (1 + rate/12) ** (years * 12).
    """
```

**Bad:**
```python
def calculate_compound_interest(principal: Decimal, rate: float, years: int) -> Decimal:
    """Calculates compound interest."""    # adds nothing
```

## Type Hints Are Not a Substitute

**Rule:** Type hints describe shape; docstrings describe meaning. Both are required for public APIs.

**Why:** `def divide(a: float, b: float) -> float` tells you nothing about what happens when `b` is zero. Docstrings fill that gap.
