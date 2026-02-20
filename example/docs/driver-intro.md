## Driver Overview

This section documents the GPU driver interfaces. All drivers share
a common initialization sequence via :func:`driver_init`.

### Supported drivers

- Intel i915/Xe
- AMD
- Virtual GEM (VGEM)
