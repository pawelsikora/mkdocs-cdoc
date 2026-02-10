/**
 * Initialize the engine subsystem.
 *
 * Must be called before :func:`engine_run`. Configure with
 * :struct:`engine_config` first.
 *
 * HowTo:
 * Always call engine_init() before any other engine function.
 * Use ENGINE_DEBUG flag for debug logging, ENGINE_TRACE for call tracing.
 * After initialization, configure with engine_config and call engine_run().
 *
 * Notes:
 * Thread safety: engine_init() is not thread-safe. Call it exactly once
 * from the main thread before spawning workers. On some platforms, calling
 * engine_init() after engine_shutdown() may leak file descriptors.
 *
 * :param flags: Initialization flags.
 * :returns: 0 on success, negative on error.
 */
int engine_init(unsigned int flags);

/**
 * Shut down the engine and release resources.
 *
 * Safe to call even if :func:`engine_init` was never called.
 */
void engine_shutdown(void);

/**
 * Get the engine name string.
 *
 * Returns a pointer to the internal name buffer. Do not free.
 *
 * Example:
 *     const char *name = engine_get_name();
 *     printf("Engine: %s\n", name);
 *
 * :param engine: Engine instance.
 * :returns: Pointer to null-terminated name string.
 */
const char *engine_get_name(struct engine_config *engine);

/**
 * Internal helper, not part of public API.
 *
 * Resets the engine state back to its initial configuration.
 * All pending operations are cancelled and buffers are flushed.
 *
 * HowTo:
 * Call after catching an unrecoverable error to restore a clean state.
 * Always pair with engine_init() afterwards to reinitialize.
 *
 * Notes:
 * This is an internal function — prefer engine_shutdown() followed by
 * engine_init() in application code. Calling with a NULL ctx is a no-op.
 *
 * :param ctx: Internal context.
 */
void __engine_reset(void *ctx);

/**
 * Engine configuration.
 *
 * Pass to :func:`engine_run` to control behavior.
 */
struct engine_config {
    /** Maximum number of worker threads. */
    int max_threads;
    /** Enable debug tracing. Set to :const:`TRUE` to enable. */
    int debug;
};
