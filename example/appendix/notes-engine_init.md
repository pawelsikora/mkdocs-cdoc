Thread safety: `engine_init()` is **not** thread-safe. Call it exactly once
from the main thread before spawning workers.

Known issue: on some platforms, calling `engine_init()` after `engine_shutdown()`
may leak file descriptors. See [issue #42](https://example.com/issues/42).
