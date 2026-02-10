Always call `engine_init()` before any other engine function.
The flags parameter controls which subsystems to activate:

- `0` — default initialization
- `ENGINE_DEBUG` — enable debug logging
- `ENGINE_TRACE` — enable call tracing

After initialization, configure with `engine_config` and call `engine_run()`.
