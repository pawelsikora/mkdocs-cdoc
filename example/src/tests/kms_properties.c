/**
 * TEST: kms_properties
 * Category: Display
 * Mega feature: KMS
 * Sub-category: Properties
 * Description: Tests for KMS property validation.
 *
 * SUBTEST: invalid-properties-legacy
 * Description: Verify invalid legacy properties are rejected.
 * Functionality: properties
 *
 * SUBTEST: invalid-properties-atomic
 * Description: Verify invalid atomic properties are rejected.
 * Functionality: properties
 *
 * SUBTEST: %s-props-%s
 * Description: Dynamic per-connector property test.
 * Functionality: properties
 */

#include "igt.h"

igt_main
{
	int fd;

	igt_fixture {
		fd = drm_open_driver_master(DRIVER_ANY);
	}

	igt_describe("Check that invalid legacy set-property calls are "
		     "correctly rejected by the kernel with appropriate "
		     "error codes for each property type.");
	igt_subtest("invalid-properties-legacy") {
		/* Try setting invalid property values */
		igt_assert(drmIoctl(fd, DRM_IOCTL_MODE_OBJ_SETPROPERTY, &bad) != 0);
	}

	igt_describe("Check that invalid atomic set-property calls are "
		     "correctly rejected by the kernel.");
	igt_subtest("invalid-properties-atomic") {
		/* Try setting invalid atomic property values */
		igt_assert(drmIoctl(fd, DRM_IOCTL_MODE_ATOMIC, &bad) != 0);
	}

	igt_subtest_with_dynamic("%s") {
		/* dynamic per-connector tests */
	}

	igt_fixture {
		close(fd);
	}
}
