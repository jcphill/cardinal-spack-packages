# cardinal-spack-packages

A Spack package repository (namespace `cardinal`) for installing
[Cardinal](https://cardinal.cels.anl.gov/) and its dependencies with
`spack install cardinal`, using Cardinal's classic Makefile build system
(not the in-progress `cmake-superbuild` branch).

## Design

Cardinal's dependencies fall into two tiers, and this repo treats them
differently:

- **PETSc, libMesh, and WASP** are slow to build, change rarely, and are
  external to Cardinal's own build (Cardinal only points at them via
  `PETSC_DIR`/`LIBMESH_DIR`/`WASP_DIR`). They're packaged here as real,
  shared, cacheable Spack packages, the same way the project's
  `moose-dev` Apptainer container pre-builds them once.
- **MOOSE itself, OpenMC, NekRS, MOAB, DAGMC, Embree, and Double-Down**
  are always compiled in-tree by Cardinal's own `config/*.mk`, from the
  exact pinned git submodule commits Cardinal's `devel` branch references
  at the time it's cloned. These are *not* independent Spack packages —
  swapping them for generically-versioned ones would risk mismatches
  with the pinned-commit integration flags Cardinal's Makefile passes.
  The `cardinal` package fetches exactly the submodules each variant
  combination needs and lets Cardinal's own Makefile build them,
  installing them straight into the final Spack prefix via
  `CONTRIB_INSTALL_DIR`.

## Packages

| Package | What it is |
|---|---|
| `cardinal` | The main package (`MakefilePackage`). Builds `cardinal-opt` (and `cardinal-dbg` if requested). |
| `wasp` | New `CMakePackage` for WASP, pinned to the commit MOOSE's `framework/contrib/wasp` submodule points at. |
| `libmesh` | Override of the builtin package: pins the exact libMesh commit MOOSE uses (the builtin's newest tagged release doesn't build against current PETSc) and adds `--enable-unique-id`. |
| `openmc-endfb71-hdf5-data` | New data-only package. Fetches the ENDF/B-VII.1 HDF5 cross-section tarball (the same one `scripts/download-openmc-cross-sections.sh` uses) and exports `OPENMC_CROSS_SECTIONS`. |
| `cray-mpich` | Override of the builtin package. Only matters if your site registers `cray-mpich` as the `mpi` provider — see [Cray / Slingshot systems](#cray--slingshot-systems) below. |

`petsc` needs no override: the builtin package's existing variants
already cover what MOOSE/Cardinal need.

## What's supported

Default build (`spack install cardinal`): `cardinal-opt` with OpenMC and
NekRS coupling both enabled, and `spack load cardinal` exporting
everything needed to run immediately — no manual environment setup.

| Variant | Default | Meaning |
|---|---|---|
| `+openmc` | on | Couple with OpenMC for neutronics |
| `+nek` | on | Couple with NekRS for CFD |
| `+dagmc` (needs `+openmc`) | off | Build OpenMC with DAGMC support for CAD/mesh geometries |
| `+double_down` (needs `+dagmc`) | off | Double-precision Embree interface for DAGMC ray tracing |
| `+cross_sections` (needs `+openmc`) | on | Install the ENDF/B-VII.1 data and set `OPENMC_CROSS_SECTIONS` |
| `+tests` | off | Fetch the `test/tests/nek_ci` submodule data needed by `run_tests` |
| `+cuda` (needs `+nek`) | off | Enable NekRS's OCCA CUDA backend for GPU-resident solves |
| `+rocm` (needs `+nek`) | off | Enable NekRS's OCCA HIP backend for GPU-resident solves on AMD GPUs |

At least one of `+openmc`/`+nek` is required.

**Out of scope:**
- The `cmake-superbuild` build path — this repo only drives the classic
  Makefile build.
- OpenCL/DPCPP backends for NekRS — only the CUDA (`+cuda`, NVIDIA
  A100s) and HIP (`+rocm`, AMD MI100s) backends are wired up and tested
  so far.

## Installing

```console
# Clone a release of Spack (this repo is validated against v1.2.2;
# Spack's unreleased `develop` branch uses a newer package API this
# repo's repo.yaml doesn't declare).
git clone --branch v1.2.2 https://github.com/spack/spack.git
. spack/share/spack/setup-env.sh

# Add this repo
git clone <this-repo-url> cardinal-spack-packages
spack repo add cardinal-spack-packages/spack_repo/cardinal

spack install cardinal
```

A full build (PETSc, libMesh, WASP, NekRS, OpenMC, and everything else)
takes on the order of 30–40 minutes. To build with a specific job limit
(e.g. on a shared login node):

```console
spack install -j16 cardinal
```

Non-default variants compose normally, e.g.:

```console
spack install cardinal +dagmc +double_down
spack install cardinal ~nek            # OpenMC-only
spack install cardinal +tests
spack install cardinal +cuda           # NekRS on NVIDIA GPUs; see GPU sections below
spack install cardinal +rocm amdgpu_target=gfx90a   # NekRS on AMD GPUs; see GPU sections below
```

## Using Cardinal after install

```console
spack load cardinal
cardinal-opt -i my_input.i
```

`spack load cardinal` sets:

- `NEKRS_HOME` (when built `+nek`) — required by Cardinal's own
  `config/check_nekrs.mk`, and always equal to the install prefix.
- `OPENMC_CROSS_SECTIONS` (when built `+openmc+cross_sections`, the
  default) — inherited automatically from the `openmc-endfb71-hdf5-data`
  dependency, pointing at its installed `cross_sections.xml`.

No other manual environment setup is needed to run a Cardinal input.

## Cray / Slingshot systems

By default, Spack will build its own generic `openmpi` to satisfy
`cardinal`'s `depends_on("mpi")`. On a Cray EX / Slingshot system (e.g.
one with `PrgEnv-gnu` and a `cray-mpich` module), that misses the
high-speed interconnect entirely and doesn't match how jobs actually get
launched (Slurm's `cray_shasta` MPI type). To use the system's MPI
instead, register it as an external in your own (not this repo's)
`packages.yaml`, e.g.:

```yaml
packages:
  cray-mpich:
    externals:
    - spec: cray-mpich@9.1.0 +wrappers
      prefix: /opt/cray/pe/mpich/9.1.0/ofi/gnu/11.2
    buildable: false
  mpi:
    require: cray-mpich
```

(Substitute the version/prefix your site's `module show cray-mpich`
reports.) This repo's `cray-mpich` override then handles a gap this
exposes: `cray-mpich`'s shared libraries need `libfabric`, but Spack
never expands an *external* package's declared dependencies into the
build graph, so nothing would otherwise tell the compiler or linker
where to find it. The override re-derives the loaded libfabric module's
library directory and injects it through the three mechanisms different
build systems in this dependency tree honor (Spack's compiler wrapper,
raw `mpicc`/`mpif90` invocations like PETSc's configure script, and
builds that pass their own competing `-rpath` flag). This is purely a
local Spack configuration concern — `cardinal`'s own `depends_on("mpi")`
stays generic so the package remains portable to non-Cray systems.

This is also the reason a full rebuild is needed after changing the MPI
provider: PETSc, libMesh, HDF5, and most of the rest of the dependency
tree all transitively depend on `mpi`, so switching providers changes
their concretized hashes.

## GPU (CUDA) systems

`spack install cardinal +cuda` enables NekRS's OCCA CUDA backend. This
needs a real CUDA toolkit registered as an external in your own
`packages.yaml` (the same local-configuration pattern as the `cray-mpich`
section above — `cardinal`'s own `depends_on` stays portable):

```yaml
packages:
  cuda:
    externals:
    - spec: cuda@13.2.0
      prefix: /opt/nvidia/hpc_sdk/Linux_x86_64/26.5/cuda/13.2
    buildable: false
```

(Substitute the version/prefix your site's CUDA module sets, e.g. via
`module show cudatoolkit`.) No `cuda_arch` needs to be set: NekRS's OCCA
layer JIT-compiles each kernel at runtime against whatever GPU it
actually finds, rather than targeting a fixed architecture at build time.

Two gaps this build needs to work around, both already handled by the
`cardinal` package itself:

- NekRS's vendored HYPRE copy doesn't compile its GPU device code
  against the Thrust headers shipped by newer CUDA toolkits (12.9+), so
  this package disables HYPRE's optional GPU-resident AMG preconditioner
  (`ENABLE_HYPRE_GPU=0`) -- NekRS's own OCCA CUDA backend (the actual
  velocity/pressure solves) is unaffected and still runs on the GPU.
- A NekRS CMake helper macro that looks up the "real" (non-MPI-wrapper)
  host compiler for `nvcc`'s `-ccbin` flag does a bare `find_program(g++)`
  at build time, which inside a Spack build sandbox finds Spack's own
  non-relocatable compiler-wrapper shim instead of the real compiler.
  Fixed by having `spack load cardinal` export
  `NEKRS_MPI_UNDERLYING_COMPILER` directly (NekRS only falls back to its
  own, wrong, build-time-recorded value if this isn't already set when
  `cardinal-opt` starts).

Validated with the bundled `test/tests/nek_standalone/channel` case on an
NVIDIA A100 pair: `active occa mode: CUDA`, a full converged solve,
postprocessor cross-checks matching the CPU build.

## GPU (ROCm/HIP) systems

`+rocm` enables NekRS's OCCA HIP backend. This needs a real ROCm install
registered as three externals in your own
`packages.yaml` (`hip` itself plus the two dependencies the ROCmPackage
mixin always pulls in, `llvm-amdgpu` and `hsa-rocr-dev` — same
local-configuration pattern as the `cray-mpich`/`cuda` sections above):

```yaml
packages:
  llvm-amdgpu:
    externals:
    - spec: llvm-amdgpu@7.14.0
      prefix: /opt/rocm-7.14.0/llvm
    buildable: false
  hsa-rocr-dev:
    externals:
    - spec: hsa-rocr-dev@7.14.0
      prefix: /opt/rocm-7.14.0
    buildable: false
  hip:
    externals:
    - spec: hip@7.14.0+rocm
      prefix: /opt/rocm-7.14.0
    buildable: false
```

(Substitute the version/prefix your site's ROCm install uses.) Unlike
`cuda_arch`, ROCmPackage's `amdgpu_target` variant has no "leave it
unset" option (it conflicts with `amdgpu_target=none` once `+rocm` is
requested), even though NekRS's OCCA layer JIT-compiles each HIP kernel
at runtime against whatever GPU it actually finds, the same as CUDA —
this package doesn't read the value or assume any particular AMD GPU, so
`+rocm` installs must pass `amdgpu_target=<your GPU's architecture>`
explicitly, e.g.:

```console
spack install cardinal +rocm amdgpu_target=gfx90a
```

The same two gaps as the CUDA case apply here too, both already handled
by the `cardinal` package itself (the HYPRE/GPU-device-code disable is
identical for both backends; the compiler-wrapper-leak fix is general to
any non-"Serial" OCCA backend, so the same `NEKRS_MPI_UNDERLYING_COMPILER`
export covers HIP as well as CUDA). One HIP-specific wrinkle: NekRS's
OCCA layer unconditionally attempts to enable HIP support at configure
time and relies on its own vendored, environment-variable-driven
`FindHIP.cmake` (not Spack's `hip` package's CMake config) to decide
whether it's actually usable, falling back to a hardcoded `/opt/rocm` if
`ROCM_PATH`/`HIP_PATH` aren't set — this package sets `ROCM_PATH`
explicitly from the registered external so the build doesn't silently
depend on ROCm being installed at that exact path.

A third, backend-agnostic gap: every NekRS case builds its own small
CMake project at the start of each run, and that project has no explicit
compiler of its own — it falls back to whatever CMake's default compiler
search finds, which on a Cray system is `cc`/`CC`, Cray's own compiler
driver. That driver injects pkg-config-derived accelerator flags based on
whichever `craype-accel-*` module is loaded in the job's environment,
which some sites' Slurm configurations load by default independent of
the job's actual GPU partition, so the driver can end up querying
pkg-config for the wrong toolkit and abort the build. This affects any
`+nek` build, not just `+cuda`/`+rocm`. Fixed by having `spack load
cardinal` export `CC`/`CXX` explicitly (to the same real MPI compiler
wrappers `nekrs.conf`'s own `CC`/`CXX` fields resolve to), which is
immune to whatever accelerator module a job's environment carries, since
CMake only falls back to a PATH search when these aren't already set.

Validated with the bundled `test/tests/nek_standalone/channel` case on an
AMD MI100: `active occa mode: HIP`, a full converged solve, postprocessor
cross-checks matching the CPU and CUDA builds.

## Known limitations

- Validated end-to-end on one Cray EX / Slingshot system with `gcc@13.3.1`,
  an NVIDIA A100 (`+cuda`), and an AMD MI100 (`+rocm`); other
  compilers/platforms/GPUs haven't been exercised.
- `+tests` fetches the test data submodule but doesn't yet wire up a
  Spack `test()`/`run_test` hook to actually invoke `run_tests`.
- No `spack test` integration.
- Spack's `libmesh` package unconditionally passes
  `--enable-gzstreams=no` (it can't point libMesh's configure at a
  specific zlib install location, so it disables gzstream support
  entirely rather than risk silently picking up a mismatched system
  zlib). This means MOOSE's default end-of-run checkpoint/recovery file
  write fails ("need gzstream to handle .gz files!!!"); pass
  `Outputs/checkpoint=false` on the command line (or set it in your
  input file) to avoid it. This is an upstream Spack `libmesh` packaging
  tradeoff, not something specific to NekRS or the `+cuda` variant.
- `cray-mpich` itself also exposes `+cuda`/`+rocm` GPU-aware-MPI variants
  that this package doesn't yet turn on (both the CUDA and HIP backends
  here only exercise device-resident compute, not GPU-aware MPI
  transfers).
