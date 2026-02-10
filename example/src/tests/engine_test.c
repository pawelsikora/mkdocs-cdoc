/**
 * Basic engine startup test.
 */
static void test_basic_startup(void)
{
	int ret;

	ret = engine_init(0);
	igt_assert(ret == 0);

	engine_shutdown();
}

/**
 * Test engine with debug mode.
 */
static void test_debug_mode(void)
{
	struct engine_config cfg = {
		.max_threads = 2,
		.debug = 1,
	};

	engine_init(ENGINE_DEBUG);
	engine_run(&cfg);
	engine_shutdown();
}
