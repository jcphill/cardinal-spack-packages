# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import os

from spack_repo.builtin.packages.cray_mpich.package import CrayMpich as BuiltinCrayMpich

from spack.package import *


def _loaded_libfabric_libdirs():
    # cray-mpich's libmpi_gnu.so needs libfabric.so.1 but has no RPATH to
    # it -- Cray relies on whatever libfabric module is loaded to put it
    # on LD_LIBRARY_PATH. Spack can't fix this through normal DAG/RPATH
    # propagation: it never adds an *external* package's declared
    # dependencies (cray-mpich depends_on("libfabric") in the builtin
    # package) into the concretized spec. Read the loaded module's lib
    # dir directly from the environment (the same way the builtin
    # package's own `external_prefix` introspects CRAY_MPICH_DIR), rather
    # than hardcoding a libfabric version, so this keeps working if the
    # loaded module changes.
    dirs = []
    for var in ("CRAY_LD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
        for entry in os.environ.get(var, "").split(":"):
            if "libfabric" in entry and os.path.isdir(entry) and entry not in dirs:
                dirs.append(entry)
    return dirs


class CrayMpich(BuiltinCrayMpich):
    def setup_dependent_build_environment(self, env, dependent_spec):
        super().setup_dependent_build_environment(env, dependent_spec)
        # Three different link styles need three different mechanisms to
        # see libfabric, since none of the DAG/RPATH-propagation Spack
        # normally relies on applies to an external dependency's own
        # undeclared needs (see _loaded_libfabric_libdirs above):
        #
        # - Spack's compiler wrapper builds its -L/-Wl,-rpath flags solely
        #   from SPACK_RPATH_DIRS/SPACK_LINK_DIRS (a DAG traversal done
        #   once, upfront), not from ambient LIBRARY_PATH/LD_RUN_PATH.
        #   SPACK_RPATH_DIRS is otherwise a plain env var set before
        #   dependency setup_dependent_build_environment hooks run, so
        #   appending to it here stacks correctly.
        # - Some dependents (e.g. PETSc's configure) invoke mpicc/mpif90
        #   directly, bypassing the compiler wrapper entirely, so
        #   SPACK_RPATH_DIRS has no effect there -- a raw gcc/gfortran
        #   invocation instead honors LIBRARY_PATH (searched for -l at
        #   link time) and LD_RUN_PATH (embedded as the output's RPATH,
        #   when the link has no competing explicit -rpath).
        # - LD_RUN_PATH is skipped whenever the link already has an
        #   explicit -rpath from elsewhere (e.g. OpenMC's CMakeLists.txt
        #   adding "-Wl,-rpath,<wasp lib dir>"), per gcc/ld's documented
        #   behavior. LD_LIBRARY_PATH is the one mechanism that resolves a
        #   shared library's own indirect NEEDED entries regardless of
        #   -rpath/-rpath-link/LD_RUN_PATH precedence, and Spack's
        #   sanitized build environment unconditionally unsets it, so it
        #   has to be set back here too.
        for libdir in _loaded_libfabric_libdirs():
            env.append_path("SPACK_RPATH_DIRS", libdir)
            env.prepend_path("LIBRARY_PATH", libdir)
            env.prepend_path("LD_RUN_PATH", libdir)
            env.prepend_path("LD_LIBRARY_PATH", libdir)
