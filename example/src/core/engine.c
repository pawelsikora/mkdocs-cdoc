/**
 * engine_run:
 * @cfg: Pointer to #engine_config.
 *
 * Run the main engine loop.
 *
 * Call engine_init() before this. Uses #engine_config.max_threads
 * to decide how many workers to spawn.
 *
 * Example:
 *
 * |[<!-- language="c" -->
 * struct engine_config cfg = { .max_threads = 4, .debug = 0 };
 * engine_init(0);
 * int rc = engine_run(&cfg);
 * engine_shutdown();
 * ]|
 *
 * Returns: Exit code.
 */
int engine_run(const struct engine_config *cfg);
