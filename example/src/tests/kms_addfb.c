/**
 * TEST: kms_addfb
 * Category: Display
 * Mega feature: KMS
 * Sub-category: Framebuffer
 * Description: Tests for the DRM framebuffer creation ioctl.
 *
 * SUBTEST: basic
 * Description: Check if addfb2 call works with a valid handle.
 * Functionality: addfb
 *
 * SUBTEST: bad-pitch
 * Description: Verify addfb2 rejects invalid pitch values.
 * Functionality: addfb
 *
 * SUBTEST: unused-handle
 * Description: Test that unused plane handles are rejected.
 * Functionality: addfb
 *
 * SUBTEST: too-high
 * Description: Ensure oversized framebuffers are rejected.
 * Functionality: addfb
 */

#include "igt.h"

/**
 * Helper to create a standard GEM buffer object.
 */
static uint32_t create_bo(int fd, int width, int height)
{
	struct drm_mode_create_dumb arg = { .size = width * height * 4 };
	igt_assert(drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &arg) == 0);
	return arg.handle;
}

igt_main
{
	int fd;
	struct drm_mode_fb_cmd2 f = {};

	igt_fixture {
		fd = drm_open_driver(DRIVER_ANY);
		igt_require(fd >= 0);
	}

	igt_describe("Check if addfb2 call works with a valid handle.");
	igt_subtest("basic") {
		/* Create a valid buffer object */
		uint32_t handle = create_bo(fd, 1024, 768);
		f.handles[0] = handle;
		f.width = 1024;
		f.height = 768;
		f.pitches[0] = 1024 * 4;
		f.pixel_format = DRM_FORMAT_XRGB8888;
		/* Submit the framebuffer via addfb2 ioctl */
		igt_assert(drmIoctl(fd, DRM_IOCTL_MODE_ADDFB2, &f) == 0);
		/* Verify we got a valid fb id */
		igt_assert(f.fb_id > 0);
		/* Clean up */
		drmIoctl(fd, DRM_IOCTL_MODE_RMFB, &f.fb_id);
		gem_close(fd, handle);
	}

	igt_describe("Verify addfb2 rejects invalid pitch values.");
	igt_subtest("bad-pitch") {
		/* Set pitch to zero which is invalid */
		f.pitches[0] = 0;
		/* Attempt addfb2 and expect failure */
		igt_assert(drmIoctl(fd, DRM_IOCTL_MODE_ADDFB2, &f) == -1);
		igt_assert(errno == EINVAL);
	}

	igt_describe("Test that unused plane handles are rejected.");
	igt_subtest("unused-handle") {
		/* Set a handle on an unused plane */
		f.handles[1] = 42;
		/* Kernel should reject extra handles for single-plane format */
		igt_assert(drmIoctl(fd, DRM_IOCTL_MODE_ADDFB2, &f) == -1);
	}

	igt_describe("Ensure oversized framebuffers are rejected.");
	igt_subtest("too-high") {
		/* Set height beyond hardware maximum */
		f.height = 65536;
		/* Attempt to create and expect rejection */
		igt_assert(drmIoctl(fd, DRM_IOCTL_MODE_ADDFB2, &f) == -1);
		igt_assert(errno == EINVAL);
	}

	igt_fixture {
		close(fd);
	}
}
