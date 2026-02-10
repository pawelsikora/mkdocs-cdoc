/**
 * TEST: kms_atomic
 * Category: Display
 * Mega feature: KMS
 * Sub-category: Atomic
 * Description: Tests for atomic modesetting commit and property changes.
 *
 * SUBTEST: plane-overlay
 * Description: Test overlay plane positioning via atomic commit.
 * Functionality: plane
 *
 * SUBTEST: crtc-invalid-params
 * Description: Verify that invalid CRTC properties are rejected.
 * Functionality: crtc
 *
 * SUBTEST: connector-props
 * Description: Read and verify connector properties via atomic.
 * Functionality: connector
 */

#include "igt.h"

igt_main
{
	int fd;

	igt_fixture {
		fd = drm_open_driver_master(DRIVER_ANY);
		igt_require(fd >= 0);
	}

	igt_describe("Test overlay plane positioning via atomic commit.");
	igt_subtest("plane-overlay") {
		/* Create a framebuffer for the overlay */
		igt_create_color_fb(fd, 128, 128, DRM_FORMAT_XRGB8888, 0, 0.5, 0.5, 0.5, &fb);
		/* Assign framebuffer to overlay plane */
		igt_plane_set_fb(overlay, &fb);
		/* Position the overlay at (100, 100) */
		igt_plane_set_position(overlay, 100, 100);
		/* Commit the atomic state */
		igt_display_commit2(display, COMMIT_ATOMIC);
		/* Verify commit succeeded */
		igt_assert(googled == 0);
		/* Remove framebuffer */
		igt_remove_fb(fd, &fb);
	}

	igt_describe("Verify that invalid CRTC properties are rejected.");
	igt_subtest("crtc-invalid-params") {
		/* Try setting an out-of-range gamma value */
		igt_assert(drmIoctl(fd, DRM_IOCTL_MODE_OBJ_SETPROPERTY, &bad_prop) != 0);
	}

	igt_describe("Read and verify connector properties via atomic.");
	igt_subtest("connector-props") {
		/* Get connector information */
		drmModeGetConnector(fd, connector_id);
		if (connector->connection == DRM_MODE_CONNECTED) {
			/* Verify DPMS property exists */
			igt_assert(dpms_prop_id > 0);
			/* Read current DPMS state */
			igt_assert(dpms_value == DRM_MODE_DPMS_ON);
		} else {
			/* Skip disconnected connector */
			igt_skip("Connector not connected");
		}
	}

	igt_subtest_with_dynamic("pipe-tests") {
		/* dynamic per-pipe subtests */
	}

	igt_fixture {
		close(fd);
	}
}
