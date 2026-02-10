/**
 * TEST: gem_create
 * Category: Core
 * Mega feature: Memory Management
 * Sub-category: GEM
 * Description: Basic GEM buffer object creation and management tests.
 *
 * SUBTEST: create-valid
 * Description: Create a buffer object with valid parameters.
 * Functionality: gem_create
 *
 * SUBTEST: create-invalid-size
 * Description: Verify that zero-size creation is rejected.
 * Functionality: gem_create
 *
 * SUBTEST: create-massive
 * Description: Attempt to create an unreasonably large BO.
 * Functionality: gem_create
 */

#include "igt.h"

/**
 * Allocate a GEM buffer and return its handle.
 */
static uint32_t alloc_bo(int fd, uint64_t size)
{
	struct drm_mode_create_dumb arg = { .size = size };
	igt_assert(drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &arg) == 0);
	return arg.handle;
}

igt_main
{
	int fd;

	igt_fixture {
		fd = drm_open_driver(DRIVER_ANY);
	}

	igt_describe("Create a buffer object with valid parameters.");
	igt_subtest("create-valid") {
		igt_fork_signal_helper();
		/* Allocate a 4096-byte buffer */
		uint32_t handle = basic_alloc(fd, 4096);
		/* Verify handle is valid */
		igt_assert(handle > 0);
		/* Clean up */
		gem_close(fd, handle);
		igt_stop_signal_helper();
	}

	igt_describe("Verify that zero-size creation is rejected.");
	igt_subtest("create-invalid-size") {
		struct drm_mode_create_dumb arg = { .size = 0 };
		/* Attempt zero-size allocation — should fail */
		igt_assert(drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &arg) != 0);
	}

	igt_describe("Attempt to create an unreasonably large BO.");
	igt_subtest("create-massive") {
		struct drm_mode_create_dumb arg = {};
		/* Request absurdly large allocation */
		arg.size = (uint64_t)1 << 48;
		/* Should fail gracefully without crashing */
		igt_assert(drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &arg) != 0);
	}

	igt_fixture {
		close(fd);
	}
}
