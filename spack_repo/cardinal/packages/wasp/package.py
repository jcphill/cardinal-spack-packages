# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack_repo.builtin.build_systems.cmake import CMakePackage

from spack.package import *


class Wasp(CMakePackage):
    """WASP (Workbench Analysis Sequence Processor) is a framework of tools
    for generating general purpose parsers and performing text processing,
    analysis, and transformation. It is used by the MOOSE framework (and
    therefore by Cardinal) for parsing MOOSE input files."""

    homepage = "https://github.com/ornl-neams-workbench/wasp"
    git = "https://github.com/ornl-neams-workbench/wasp.git"

    maintainers("jcphill")

    license("LGPL-2.1-or-later")

    # Pinned to the commit referenced by MOOSE's framework/contrib/wasp
    # submodule for the MOOSE commit Cardinal currently pulls in. Update
    # this alongside the `moose` resource/submodule pin in the `cardinal`
    # package. To find the current pin:
    #   git -C <moose-checkout> ls-tree HEAD framework/contrib/wasp
    version("2025-08-25", commit="ce25dcde73ba81c70c330204ea5bf856762b95ac", submodules=True)

    depends_on("cxx", type="build")
    depends_on("cmake@3.20:", type="build")

    # waspcore/utils.h calls ::mkdir() but never includes <sys/stat.h>
    # (only <stdio.h>/<cstdlib>/etc.), so it only compiles when a
    # consumer's translation unit happens to pull in <sys/stat.h> first --
    # which doesn't hold for MOOSE's framework/build/header_symlinks/
    # Builder.h -> .../hit.h -> wasphit/HITInterpreter.h ->
    # waspcore/TreeNodePool.h -> waspcore/utils.h include chain.
    patch("sys_stat_include.patch")

    def cmake_args(self):
        # Mirrors MOOSE's scripts/configure_wasp.sh, which is what builds
        # the WASP that Cardinal/MOOSE link against.
        return [
            self.define("wasp_ENABLE_ALL_PACKAGES", False),
            self.define("wasp_ENABLE_wasphit", True),
            self.define("wasp_ENABLE_wasplsp", True),
            self.define("wasp_ENABLE_waspsiren", True),
            self.define("wasp_ENABLE_waspplot", True),
            self.define("wasp_ENABLE_testframework", False),
            self.define("wasp_ENABLE_TESTS", False),
            self.define("BUILD_SHARED_LIBS", True),
            self.define("DISABLE_HIT_TYPE_PROMOTION", True),
        ]
