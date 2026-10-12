# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import glob
import os
import re

from spack_repo.builtin.build_systems.cuda import CudaPackage
from spack_repo.builtin.build_systems.makefile import MakefilePackage
from spack_repo.builtin.build_systems.rocm import ROCmPackage

from spack.package import *


def submodules(package):
    # Mirrors scripts/get-dependencies.sh, minus the submodules replaced by
    # proper Spack dependencies (petsc/libmesh/wasp -- MOOSE_DIR only needs
    # the framework/modules sources).
    mods = ["contrib/moose", "contrib/nuclear_data"]
    if package is None:
        return mods
    if package.spec.satisfies("+nek"):
        mods.append("contrib/nekRS")
    if package.spec.satisfies("+openmc"):
        mods.append("contrib/openmc")
    if package.spec.satisfies("+dagmc"):
        mods += ["contrib/DAGMC", "contrib/moab"]
        if package.spec.satisfies("+double_down"):
            mods += ["contrib/double-down", "contrib/embree"]
    if package.spec.satisfies("+tests"):
        mods.append("test/tests/nek_ci")
    return mods


class Cardinal(MakefilePackage, CudaPackage, ROCmPackage):
    """Cardinal is a MOOSE-based application for coupling MOOSE-based codes
    with NekRS and OpenMC for multiphysics simulation of nuclear reactors."""

    homepage = "https://cardinal.cels.anl.gov/"
    git = "https://github.com/neams-th-coe/cardinal.git"

    maintainers("jcphill")

    # Cardinal has no tagged releases in active use; devel is the branch
    # the project actually develops and tests against.
    version("devel", branch="devel", submodules=submodules, get_full_repo=False)

    # libMesh's Autotools build links its legacy, bundled ExodusII sources
    # (contrib/exodusii/Lib), which predate the "partial I/O" API
    # (ex_get_partial_set and friends) that a fully-capable
    # Nemesis_IO::get_nemio_helper() needs; that API only exists in
    # libMesh's separate, unused contrib/exodusii/v8.11 copy. MOOSE's
    # SolutionUserObjectBase.C calls get_nemio_helper() unconditionally
    # whenever LIBMESH_HAVE_EXODUS_API is defined, so it has to be patched
    # out. Replaced with a mooseError() (matching nemesis_copy_solution.patch
    # below) rather than silently leaving the block-name<->id lookup map
    # empty, so reading a nemesis-format solution file fails immediately
    # with a clear message instead of leaving callers of
    # getBlockNamesToIds()/getBlockIdsToNames() to find an empty map.
    patch("nemesis_block_id_map.patch")

    # Same root cause as nemesis_block_id_map.patch, same file: libMesh
    # only compiles Nemesis_IO::copy_elemental_solution()/
    # copy_scalar_solution() under "#if defined(LIBMESH_HAVE_EXODUS_API) &&
    # defined(LIBMESH_HAVE_NEMESIS_API)", but SolutionUserObjectBase.C
    # calls them unconditionally through generic ("auto &") lambdas
    # instantiated for *_nemesis_io regardless of whether a run actually
    # reads a nemesis-format file. With libmesh~nemesis (required -- see
    # the ~nemesis/~triangle comment on the libmesh dependency below) this
    # is an undefined-reference link failure. Replaces each such call site
    # with mooseError(), which only changes behavior for the (already
    # unsupported) case of reading a nemesis-format solution file.
    patch("nemesis_copy_solution.patch")

    # NekRS's vendored HYPRE copy (contrib/nekRS/3rd_party/hypre) does not
    # compile its GPU device code (HYPRE_BUILD_DEVICE, gated by NekRS's own
    # "ENABLE_HYPRE_GPU AND (OCCA_CUDA_ENABLED OR OCCA_HIP_ENABLED)" CMake
    # condition) against the Thrust headers shipped by newer CUDA toolkits
    # (12.9+). Disabling it only drops HYPRE's optional GPU-resident AMG
    # preconditioner; NekRS's own OCCA CUDA/HIP backends (the
    # velocity/pressure solves) are unaffected. A no-op when neither +cuda
    # nor +rocm is requested.
    patch("nekrs_disable_hypre_gpu.patch")

    variant("openmc", default=True, description="Couple with OpenMC for neutronics")
    variant("nek", default=True, description="Couple with NekRS for CFD")
    variant(
        "dagmc",
        default=False,
        description="Build OpenMC with DAGMC support for CAD/mesh geometries",
        when="+openmc",
    )
    variant(
        "double_down",
        default=False,
        description="Use the double-precision Embree interface for DAGMC ray tracing",
        when="+dagmc",
    )
    variant(
        "cross_sections",
        default=True,
        description="Install ENDF/B-VII.1 HDF5 data and set OPENMC_CROSS_SECTIONS",
        when="+openmc",
    )
    variant("tests", default=False, description="Fetch test data needed by run_tests")

    # "cuda"/"cuda_arch" come from the CudaPackage mixin. cuda_arch doesn't
    # need to be set: NekRS's OCCA layer JIT-compiles each kernel at
    # runtime (plain "nvcc" invocation, contrib/nekRS/3rd_party/occa/src/
    # occa/internal/modes/cuda/device.cpp) after querying the device's
    # compute capability at startup -- there's no static "-arch=sm_80"
    # flag to set at build time.
    conflicts("+cuda", when="~nek", msg="+cuda only affects NekRS's OCCA backend")

    # Same story for "+rocm" (ROCmPackage mixin): OCCA's HIP backend
    # JIT-compiles each kernel at runtime against whatever device it finds
    # (occa::hip::getDeviceArch()), with no static "--offload-arch=gfx908"
    # flag needed at build time, and nothing in this package reads the
    # "amdgpu_target" variant ROCmPackage provides. Unlike cuda_arch,
    # though, ROCmPackage requires a non-"none" value for it whenever
    # +rocm is set, with no "auto-detect at runtime" option -- so
    # `+rocm` installs must pass `amdgpu_target=<your GPU's architecture>`
    # explicitly (e.g. `amdgpu_target=gfx90a`); this package doesn't
    # assume any particular AMD GPU.
    conflicts("+rocm", when="~nek", msg="+rocm only affects NekRS's OCCA backend")
    # NekRS picks one default OCCA backend at build time (CUDA takes
    # priority over HIP: contrib/nekRS/CMakeLists.txt's
    # "if(OCCA_CUDA_ENABLED) ... elseif(OCCA_HIP_ENABLED)"), so enabling
    # both would silently build HIP support that can never be selected.
    conflicts("+cuda+rocm", msg="NekRS only runs one OCCA GPU backend per build")

    # Spack only sets up the compiler-wrapper environment
    # (SPACK_COMPILER_WRAPPER_PATH etc.) for languages a package
    # depends_on -- NekRS's CMake configure (invoked from this package's
    # own build() via Cardinal's Makefile) runs a Fortran compiler sanity
    # check, so all three are required here.
    depends_on("c", type="build")
    depends_on("cxx", type="build")
    depends_on("fortran", type="build")

    # MOOSE's framework/contrib/hit Python bindings are a pre-generated
    # Cython .cpp file; moose.mk compiles it against whatever "python3-config"
    # resolves first on PATH, with no Spack dependency of its own to pin
    # that down. A system default below Python 3.8 (what the bundled
    # Cython output itself requires) fails to compile outright, so this
    # package needs its own known-good Python pulled in and put ahead of
    # it on PATH (see setup_build_environment below).
    depends_on("python@3.8:", type="build")
    # moose.mk's MooseRevision.h generation step (scripts/get_repo_revision.py)
    # imports this unconditionally on Python 3.7+ and is not allowed to fail
    # silently (unlike scripts/premake.py's own optional pyyaml import,
    # which moose.mk explicitly ignores failures from). depends_on (rather
    # than relying on whatever's already on the chosen Python's path) makes
    # it an extension of the same Python selected above.
    depends_on("py-packaging", type="build")

    depends_on("mpi")
    depends_on("petsc+mpi+hypre+mumps+metis+hdf5", type="link")
    # +hl: OpenMC's CMake asks FindHDF5 for the HL component; without it
    # the Spack-built hdf5 doesn't export an hdf5_hl-shared target.
    depends_on("hdf5+hl+mpi", type="link")
    # MOOSE's framework headers unconditionally #include several of
    # libMesh's optional/bundled-library headers, regardless of which
    # Cardinal variant is active:
    #   +exodusii  - framework/contrib/exodiff includes <libmesh/exodusII.h>
    #   +eigen     - framework/build/header_symlinks/EigenADReal.h
    #   +fparser   - framework/include/utils/InputParameters.h's non-fparser
    #                fallback stub for FunctionParserBase has a pre-existing
    #                MOOSE bug (a missing semicolon) that only the
    #                LIBMESH_HAVE_FPARSER #ifdef branch avoids
    #   +nanoflann - framework/build/header_symlinks/MooseMesh.h includes
    #                <libmesh/nanoflann.hpp>
    #   +slepc     - modules/stochastic_tools/.../PODMapping.h includes
    #                <slepcsvd.h> (stochastic_tools is always compiled);
    #                slepc is a real external package, not bundled, hence
    #                the separate depends_on("slepc") below
    # The remaining bundled libMesh libraries (capnproto/gmv/laspack/
    # libhilbert/poly2tri/qhull/sfc/tetgen) are enabled too: each is a
    # free, self-contained vendored-code switch with no extra Spack
    # dependency, so there's no reason to track down which MOOSE headers
    # need which one individually. Two exceptions:
    #  - +nemesis alongside +exodusii fails to link libMesh itself
    #    (undefined ex_get_partial_*/ex__put_nemesis_version references --
    #    an ABI mismatch between libMesh's bundled nemesis and exodusii
    #    code), and nothing in Cardinal/MOOSE needs it.
    #  - +triangle makes framework/src/constraints/MortarSegmentHelper.C's
    #    "#ifdef LIBMESH_HAVE_TRIANGLE" branch reference
    #    `TriangleInterface` unqualified instead of
    #    `libMesh::TriangleInterface`, a dormant MOOSE bug the officially
    #    supported MOOSE/Cardinal configuration avoids by building libMesh
    #    with +poly2tri instead (which satisfies the same header guard).
    # ~triangle/~nemesis are written explicitly (not just omitted) so
    # Spack's reuse-concretization can't pick an already-built libmesh
    # that still has either one enabled.
    depends_on(
        "libmesh+petsc+metaphysicl+hdf5+metis+exodusii+eigen+fparser"
        "+nanoflann+capnproto+gmv+laspack+libhilbert+poly2tri+slepc"
        "+qhull+sfc+tetgen~triangle~nemesis threads=openmp",
        type="link",
    )
    depends_on("slepc", type="link")
    depends_on("wasp", type="link")
    depends_on("eigen", type="build", when="+dagmc")
    depends_on("fmt", type="link", when="+openmc")
    depends_on("pugixml", type="link", when="+openmc")
    depends_on(
        "openmc-endfb71-hdf5-data", type="run", when="+openmc+cross_sections"
    )

    conflicts("~openmc~nek", msg="Cardinal needs at least one of +openmc or +nek")

    def setup_build_environment(self, env):
        spec = self.spec

        # The slow-changing, Spack-shared half of the dependency stack:
        # Cardinal/MOOSE only ever point at these via *_DIR, never vendor
        # or build them. Everything else (MOOSE framework, OpenMC, NekRS,
        # MOAB, DAGMC, Embree, Double-Down) is compiled in-tree from the
        # pinned submodule sources fetched above.
        env.set("PETSC_DIR", spec["petsc"].prefix)
        env.set("LIBMESH_DIR", spec["libmesh"].prefix)
        env.set("WASP_DIR", spec["wasp"].prefix)
        env.set("HDF5_ROOT", spec["hdf5"].prefix)

        # Route OpenMC/NekRS/MOAB/DAGMC/Embree/Double-Down installs
        # straight into the final Spack prefix (Makefile:77); this also
        # makes NEKRS_HOME == CONTRIB_INSTALL_DIR hold both now (so
        # config/check_nekrs.mk's build-time check passes) and later via
        # setup_run_environment below.
        env.set("CONTRIB_INSTALL_DIR", self.prefix)
        if spec.satisfies("+nek"):
            env.set("NEKRS_HOME", self.prefix)

        # OpenMC's CMake consumes FETCHCONTENT_SOURCE_DIR_FMT/_PUGIXML
        # (config/check_deps.mk derives these from FMT_DIR/PUGI_DIR, which
        # otherwise default to the unpopulated contrib/fmt and
        # contrib/pugixml submodule paths this package doesn't fetch), so
        # point them at the Spack-built fmt/pugixml.
        if spec.satisfies("+openmc"):
            env.set("FMT_DIR", spec["fmt"].prefix)
            env.set("PUGI_DIR", spec["pugixml"].prefix)

        # Spack doesn't put a type="build" python dependency's bin/ on PATH
        # automatically (that only happens for packages that *extend*
        # python); do it explicitly so moose.mk's "python3-config" (see the
        # depends_on above) finds this Python ahead of whatever the system
        # provides.
        env.prepend_path("PATH", spec["python"].prefix.bin)

        jobs = str(make_jobs)
        env.set("LIBMESH_JOBS", jobs)
        env.set("MOOSE_JOBS", jobs)
        env.set("JOBS", jobs)

        if spec.satisfies("+cuda"):
            self._setup_cuda_environment(env)
        if spec.satisfies("+rocm"):
            self._setup_rocm_environment(env)

    def _setup_cuda_environment(self, env):
        # NekRS's CMake configure (config/nekrs.mk) sets CMAKE_C/
        # CXX_COMPILER to the real mpicc/mpicxx directly rather than
        # through Spack's compiler wrapper (see the cray_mpich package
        # override), so Spack's automatic RPATH propagation doesn't apply.
        # CUDA's own setup_dependent_build_environment only sets
        # CUDA_HOME/NVHPC_CUDA_HOME, which NekRS's legacy
        # "find_package(CUDA REQUIRED)" doesn't consult -- it finds nvcc
        # via PATH and libcudart via CUDA_TOOLKIT_ROOT_DIR/standard search,
        # so PATH is what has to carry this. Also needed at OCCA's
        # *runtime* JIT-compile step (it execs "nvcc" directly), hence the
        # same wiring repeated in setup_run_environment below.
        cuda_prefix = self.spec["cuda"].prefix
        env.prepend_path("PATH", cuda_prefix.bin)
        # A raw mpicc/mpicxx link honors LIBRARY_PATH (search path for -l
        # at link time) and LD_RUN_PATH (embedded as the output's RPATH,
        # unless some other part of the link already passes an explicit
        # -rpath); LD_LIBRARY_PATH resolves a shared library's own
        # indirect dependencies (libcudart.so's own needed libs)
        # regardless of which of those two applies.
        env.prepend_path("LIBRARY_PATH", cuda_prefix.lib64)
        env.prepend_path("LD_RUN_PATH", cuda_prefix.lib64)
        env.prepend_path("LD_LIBRARY_PATH", cuda_prefix.lib64)

    def _setup_rocm_environment(self, env):
        # Same story as _setup_cuda_environment, for HIP: NekRS's
        # CMakeLists.txt unconditionally forces OCCA_ENABLE_HIP=ON and
        # lets OCCA's bundled cmake/FindHIP.cmake (a legacy find module,
        # not Spack's "hip" package's CMake config) decide whether HIP is
        # actually usable. FindHIP.cmake looks for "hipconfig" via "ENV
        # ROCM_PATH"/"ENV HIP_PATH" first, falling back to a hardcoded
        # "/opt/rocm" -- setting ROCM_PATH explicitly from the registered
        # external keeps this portable to sites where ROCm isn't installed
        # at that literal path (build()'s OCCA_HIP_ENABLED=0 is what
        # actually disables HIP when +rocm isn't requested). The runtime
        # JIT compile execs "hipcc" directly, same as "nvcc" for CUDA,
        # hence the same wiring repeated in setup_run_environment below.
        hip_prefix = self.spec["hip"].prefix
        env.set("ROCM_PATH", hip_prefix)
        env.prepend_path("PATH", hip_prefix.bin)
        env.prepend_path("LIBRARY_PATH", hip_prefix.lib)
        env.prepend_path("LD_RUN_PATH", hip_prefix.lib)
        env.prepend_path("LD_LIBRARY_PATH", hip_prefix.lib)

    def _enable(self, variant):
        return "yes" if self.spec.satisfies(f"+{variant}") else "no"

    def build(self, spec, prefix):
        make(
            f"ENABLE_OPENMC={self._enable('openmc')}",
            f"ENABLE_NEK={self._enable('nek')}",
            f"ENABLE_DAGMC={self._enable('dagmc')}",
            f"ENABLE_DOUBLE_DOWN={self._enable('double_down')}",
            f"OCCA_CUDA_ENABLED={'1' if spec.satisfies('+cuda') else '0'}",
            f"OCCA_HIP_ENABLED={'1' if spec.satisfies('+rocm') else '0'}",
        )

    def install(self, spec, prefix):
        # Cardinal has no `make install` target (OpenMC/NekRS/etc. are
        # already in `prefix` via CONTRIB_INSTALL_DIR from build()), so
        # cardinal-opt (and cardinal-dbg, under METHOD=dbg) just need
        # copying over by hand.
        #
        # cardinal-opt is not self-contained: like every MOOSE-based app it
        # dynamically links libmoose-opt.so, its own libcardinal-opt.so/
        # libcardinal_test-opt.so, libhit-opt.so/libpcre-opt.so, and one
        # shared library per enabled MOOSE module -- none of which
        # Cardinal's Makefile installs anywhere; its RPATH points straight
        # at the (temporary) build tree. Rather than hardcoding that list
        # of build-tree subdirectories (fragile to the exact set of MOOSE
        # modules Cardinal enables), find them the way the loader would:
        # run ldd on the still-in-place build-tree binary, collect the
        # directories of every dependency that resolved inside the stage,
        # and copy those libraries into prefix.lib -- already on
        # cardinal-opt's RPATH (where CONTRIB_INSTALL_DIR=self.prefix put
        # NekRS/OpenMC/ADIOS2 during build()), so no RPATH surgery is
        # needed.
        mkdirp(prefix.bin)
        mkdirp(prefix.lib)

        binaries = [join_path(self.stage.source_path, "cardinal-opt")]
        dbg = join_path(self.stage.source_path, "cardinal-dbg")
        if os.path.exists(dbg):
            binaries.append(dbg)

        ldd = which("ldd", required=True)
        cp = which("cp", required=True)
        lib_dirs = set()
        for binary in binaries:
            output = ldd(binary, output=str, error=str)
            for line in output.splitlines():
                if "=>" not in line:
                    continue
                resolved = line.split("=>", 1)[1].strip().split()[0]
                if resolved in ("not", ""):
                    continue
                if resolved.startswith(self.stage.source_path):
                    lib_dirs.add(os.path.dirname(resolved))

        for lib_dir in lib_dirs:
            libs = glob.glob(join_path(lib_dir, "*.so*"))
            if libs:
                cp("-a", *libs, prefix.lib)

        for binary in binaries:
            install(binary, prefix.bin)

        # MOOSE also expects certain modules' "data" directories at
        # PREFIX/share/<name>/data (Registry.C's determineDataFilePath(),
        # which mooseErrors at startup if missing once the binary looks
        # installed). Cardinal's Makefile never installs these. Rather
        # than hardcoding the two current call sites
        # (registerAppDataFilePath("moose") in framework/src/base/Moose.C,
        # registerAppDataFilePath("solid_mechanics") in
        # modules/solid_mechanics/src/base/SolidMechanicsApp.C), discover
        # them the way MOOSE itself does: find every
        # registerAppDataFilePath("name") call under contrib/moose and
        # copy that call's sibling "../../data" directory, if present, to
        # prefix/share/<name>/data.
        register_re = re.compile(r'registerAppDataFilePath\("([a-z0-9_]+)"\)')
        moose_dir = join_path(self.stage.source_path, "contrib", "moose")
        for root, _dirs, files in os.walk(moose_dir):
            for fname in files:
                if not fname.endswith(".C"):
                    continue
                with open(join_path(root, fname), errors="ignore") as f:
                    names = register_re.findall(f.read())
                for name in names:
                    data_dir = os.path.normpath(join_path(root, "..", "..", "data"))
                    if os.path.isdir(data_dir):
                        dest_dir = join_path(prefix.share, name)
                        mkdirp(dest_dir)
                        cp("-a", data_dir, dest_dir)

    def setup_run_environment(self, env):
        if self.spec.satisfies("+nek"):
            env.set("NEKRS_HOME", self.prefix)

            # Every NekRS case builds its own small CMake project at the
            # start of each run (the per-case ".cache/udf" build), and
            # that CMakeLists.txt has no explicit CMAKE_C_COMPILER/
            # CXX_COMPILER of its own -- it relies on CMake's default
            # detection (CC/CXX env vars, else generic names like "cc" on
            # PATH). On a Cray system "cc" on PATH is Cray's own PrgEnv
            # compiler driver, which injects pkg-config-derived
            # accelerator flags based on whatever craype-accel-* module is
            # loaded in the job's environment -- some sites' Slurm
            # configurations load such a module by default independent of
            # the job's actual GPU partition, so the driver can end up
            # querying pkg-config for a toolkit that has nothing to do
            # with the node the job is running on and abort the whole udf
            # build. This applies to any +nek build, not just +cuda/+rocm.
            # Exporting CC/CXX explicitly (to the same real MPI compiler
            # wrappers nekrs.conf's own CC/CXX fields resolve to) makes
            # this immune to whatever accelerator module happens to be
            # loaded, since CMake only falls back to a PATH search when
            # these aren't already set.
            mpi_prefix = self.spec["mpi"].prefix
            env.set("CC", mpi_prefix.bin.mpicc)
            env.set("CXX", mpi_prefix.bin.mpicxx)

            # NekRS resolves the "underlying" (non-MPI-wrapper) host
            # compiler it needs for nvcc's/hipcc's "-ccbin"-equivalent
            # flag, and for OCCA's host-compiler-vendor check, via a CMake
            # macro (cmake/utils.cmake's __MPI_underlying_compiler) that
            # does a bare "find_program(g++)" at build time -- inside a
            # Spack build sandbox this resolves to Spack's own
            # non-relocatable compiler-wrapper shim, which is recorded
            # into nekrs.conf and would fail at runtime once the build
            # sandbox no longer exists. NekRS's own
            # src/platform/setEnvVars.hpp only applies that recorded value
            # if NEKRS_MPI_UNDERLYING_COMPILER isn't already set when
            # cardinal-opt starts, so setting it here (to the real host
            # C++ compiler) bypasses the bad build-time value entirely.
            # src/platform/device.cpp only consumes it when the active
            # occa mode isn't "Serial" (i.e. any GPU backend, or a
            # non-default OpenMP mode), so setting it unconditionally
            # whenever NekRS is built is harmless for a CPU-only install.
            env.set("NEKRS_MPI_UNDERLYING_COMPILER", self.compiler.cxx)
        if self.spec.satisfies("+cuda"):
            # OCCA JIT-compiles each CUDA kernel at first use by exec'ing
            # "nvcc", and the installed cardinal-opt/nekrs binaries need
            # libcudart.so at process startup -- neither is something
            # "spack load cardinal" gets for free, since CUDA is an
            # external package outside the Spack store whose own
            # setup_dependent_run_environment only sets CUDA_HOME.
            cuda_prefix = self.spec["cuda"].prefix
            env.prepend_path("PATH", cuda_prefix.bin)
            env.prepend_path("LD_LIBRARY_PATH", cuda_prefix.lib64)
        if self.spec.satisfies("+rocm"):
            # Same story as the +cuda block above, for HIP: OCCA
            # JIT-compiles each kernel at first use by exec'ing "hipcc",
            # and the installed binaries need libamdhip64.so at startup.
            hip_prefix = self.spec["hip"].prefix
            env.prepend_path("PATH", hip_prefix.bin)
            env.prepend_path("LD_LIBRARY_PATH", hip_prefix.lib)

    @run_after("install")
    def check_single_hdf5(self):
        # Spack's concretizer guarantees only one "hdf5" node in cardinal's
        # dependency DAG (petsc and libmesh both depend_on("hdf5+mpi")
        # rather than vendoring their own copy). The risk this guards
        # against is a sub-build (OpenMC/MOAB/DAGMC/NekRS's own CMake
        # find_package(HDF5) calls) independently discovering a different
        # HDF5 if HDF5_ROOT/CMAKE_PREFIX_PATH don't reach it, producing a
        # cardinal-opt that's internally inconsistent. Checking the final
        # linked binary with ldd verifies what's actually in use at
        # runtime.
        hdf5_prefix = os.path.realpath(self.spec["hdf5"].prefix)
        ldd = which("ldd", required=True)
        binaries = [join_path(self.prefix.bin, "cardinal-opt")]
        dbg = join_path(self.prefix.bin, "cardinal-dbg")
        if os.path.exists(dbg):
            binaries.append(dbg)
        for binary in binaries:
            output = ldd(binary, output=str, error=str)
            bad = []
            for line in output.splitlines():
                if "libhdf5" not in line or "=>" not in line:
                    continue
                resolved = line.split("=>", 1)[1].strip().split()[0]
                if resolved in ("not", ""):
                    continue
                resolved = os.path.realpath(resolved)
                if not resolved.startswith(hdf5_prefix):
                    bad.append((line.strip(), resolved))
            if bad:
                details = "\n".join(f"  {line}  (resolves to {r})" for line, r in bad)
                raise InstallError(
                    f"{binary} links against HDF5 outside the Spack-managed "
                    f"hdf5 package at {hdf5_prefix}:\n{details}\n"
                    "This means some sub-build (OpenMC/MOAB/DAGMC/NekRS's own "
                    "CMake) found a different HDF5 via its own search path "
                    "instead of the one HDF5_ROOT/CMAKE_PREFIX_PATH point at."
                )
