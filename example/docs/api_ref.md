# API Reference Manual

Welcome to the igt-gpu-tools API reference.

The reference covers two areas:

- **[Core Library](api_reference/lib)** (`lib/`) — shared helpers for DRM testing, KMS,
  framebuffer management, debugfs, GPU-specific support, and more.
  These are the building blocks that all IGT tests rely on.
- **[Tests](api_reference/tests)** (`tests/`) — the full test catalog with structured metadata,
  subtest listings, and "By Category" / "By Functionality" group pages.

Each library module below links to its generated API page with function
signatures, parameter tables, and cross-referenced symbols. Use the A–Z
index on each overview page to jump directly to any symbol.

---

## Core / Xe API Reference

| Module | Source | Description |
|--------|--------|-------------|
| **DMABUF Sync File** | :file:`dmabuf_sync_file.c` | DMABUF importing/exporting fencing support library |
| **drmtest** | :file:`drmtest.c` | Base library for drm tests and tools |
| **ALSA** | :file:`igt_alsa.c` | Library with ALSA helpers |
| **Audio** | :file:`igt_audio.c` | Library for audio-related tests |
| **aux** | :file:`igt_aux.c` | Auxiliary libraries and support functions |
| **Chamelium** | :file:`igt_chamelium.c` | Library for using the Chamelium into igt tests |
| **Collection** | :file:`igt_collection.c` | Generic combinatorics library |
| **Core** | :file:`igt_core.c` | Core i-g-t testing support |
| **CRC** | :file:`igt_crc.c` | igt crc tables and calculation functions |
| **debugfs** | :file:`igt_debugfs.c` | Support code for debugfs features |
| **igt_device** | :file:`igt_device.c` | igt_device |
| **Device selection** | :file:`igt_device_scan.c` | Device scanning and selection |
| **Draw** | :file:`igt_draw.c` | drawing helpers for tests |
| **Dummyload** | :file:`igt_dummyload.c` | Library for submitting GPU workloads |
| **Framebuffer** | :file:`igt_fb.c` | Framebuffer handling and drawing library |
| **Frame** | :file:`igt_frame.c` | Library for frame-related tests |
| **fs** | :file:`igt_fs.c` | Helpers for file operations |
| **GT** | :file:`igt_gt.c` | GT support library |
| **Hook support** | :file:`igt_hook.c` | Support for running a hook script on test execution |
| **kmod** | :file:`igt_kmod.c` | Wrappers around libkmod for module loading/unloading |
| **KMS** | :file:`igt_kms.c` | Kernel modesetting support library |
| **IGT List** | :file:`igt_list.c` | a list implementation inspired by the kernel |
| **IGT Map** | :file:`igt_map.c` | a linear-reprobing hashmap implementation |
| **msm** | :file:`igt_msm.c` | msm support library |
| **pipe_crc** | :file:`igt_pipe_crc.c` | Pipe CRC support |
| **Power Management** | :file:`igt_power.c` | Power Management related helpers |
| **Primes** | :file:`igt_primes.c` | Prime numbers helper library |
| **Random** | :file:`igt_rand.c` | Random numbers helper library |
| **Stats** | :file:`igt_stats.c` | Tools for statistical analysis |
| **syncobj** | :file:`igt_syncobj.c` | Library with syncobj helpers |
| **sysfs** | :file:`igt_sysfs.c` | Support code for sysfs features |
| **VC4** | :file:`igt_vc4.c` | VC4 support library |
| **VGEM** | :file:`igt_vgem.c` | VGEM support library |
| **x86** | :file:`igt_x86.c` | x86 helper library |
| **Intel allocator** | :file:`intel_allocator.c` | igt implementation of allocator |
| **Batch Buffer** | :file:`intel_batchbuffer.c` | Batchbuffer and blitter support |
| **Buffer operations** | :file:`intel_bufops.c` | Buffer operation on tiled surfaces |
| **Chipset** | :file:`intel_chipset.c` | Feature macros and chipset helpers |
| **I/O** | :file:`intel_mmio.c` | Register access and sideband I/O library |
| **ioctl wrappers** | :file:`ioctl_wrappers.c` | ioctl wrappers and related functions |
| **SW Sync** | :file:`sw_sync.c` | Software sync (fencing) support library |

## i915 API Reference

| Module | Source | Description |
|--------|--------|-------------|
| **GEM Create** | :file:`gem.c` | Helpers for dealing with objects creation |
| **GEM Context** | :file:`gem_context.c` | Helpers for dealing with contexts |
| **GEM Engine Topology** | :file:`gem_engine_topology.c` | Helpers for dealing engine topology |
| **GEM Scheduler** | :file:`gem_scheduler.c` | Helpers for querying scheduler capabilities |
| **GEM Submission** | :file:`gem_submission.c` | Helpers for determining submission method |
| **Blitter library** | :file:`intel_blt.c` | i915/xe blitter library |
| **I915 GPU CRC** | :file:`i915_crc.c` | i915 gpu crc |
| **Intel Context Wrapper** | :file:`intel_ctx.c` | Wrapper structs for dealing with contexts |


---

This documentation is auto-generated from C/C++ source comments using
[mkdocs-cdoc](https://github.com/pawelsikora/mkdocs-cdoc).
