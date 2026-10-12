# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import os

from spack_repo.builtin.packages.libmesh.package import Libmesh as BuiltinLibmesh

from spack.package import *


class Libmesh(BuiltinLibmesh):
    """libMesh, built with the one extra configure flag MOOSE's own
    scripts/configure_libmesh.sh always passes (--enable-unique-id) that
    isn't otherwise reachable through the upstream package's variants.
    Everything else MOOSE needs maps onto existing variants directly:
    +petsc +metaphysicl +hdf5 +metis and threads=openmp give the same
    configuration MOOSE's build scripts produce (the "openmp" thread
    variant already expands to --enable-openmp --with-thread-model=pthread
    --enable-pthreads, matching libMesh's own coupling of OpenMP to
    pthreads).

    The builtin package's newest tagged release (1.8.4) does not build
    against recent PETSc: it calls PetscErrorMessage() with the pre-3.25
    signature (`char **` where PETSc 3.25+ wants `const char **`; see
    include/libmesh/petsc_solver_exception.h). MOOSE's own libmesh
    submodule tracks a point past 1.8.4 on libMesh's rolling branch that
    already carries the fix, so we pin to that exact commit instead of
    the stale release. Update this alongside the `petsc`/`wasp` pins in
    the `cardinal` package. To find the current pin:
      git -C <moose-checkout> ls-tree HEAD libmesh
    """

    version(
        "2026-07-30", commit="90766057ef390adc9968b529e8ded2a87b0a77c7", submodules=True
    )

    def configure_args(self):
        args = super().configure_args() + ["--enable-unique-id"]
        # libMesh's ./configure correctly resolves CC/CXX to the real
        # mpicc/mpicxx, but not FC: that one falls back to Spack's own
        # compiler-wrapper script, baked as an absolute path into
        # libMesh's installed libmesh-config/Make.common. Cardinal's
        # top-level Makefile reads that value back out (as libmesh_F90 /
        # LIBMESH_F90_LIST) to compile NekRS's legacy Nek5000 Fortran core
        # -- and NekRS recompiles that same core again at *runtime* on
        # first use (buildNekInterface), long after the Spack build
        # sandbox exists, so the wrapper fails with "Spack compiler must
        # be run from Spack!". Force FC explicitly to the real MPI
        # Fortran wrapper, matching what CC/CXX already resolve to.
        # MPIF90 is set generically by every mainstream MPI provider's own
        # Spack package in setup_run_environment, not specific to
        # cray-mpich, so this stays portable to non-Cray systems.
        mpif90 = os.environ.get("MPIF90")
        if mpif90:
            args.append(f"FC={mpif90}")
        return args
