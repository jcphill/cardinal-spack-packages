# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack.package import *


class OpenmcEndfb71Hdf5Data(Package):
    """ENDF/B-VII.1 continuous-energy nuclear data in OpenMC's native HDF5
    format, mirrored by Argonne National Laboratory. This is the dataset
    Cardinal's own scripts/download-openmc-cross-sections.sh fetches, and
    what OpenMC's OPENMC_CROSS_SECTIONS environment variable needs to point
    at to run almost any OpenMC- or Cardinal-with-OpenMC input."""

    homepage = "https://docs.openmc.org/en/stable/usersguide/cross_sections.html"
    url = "https://anl.box.com/shared/static/9igk353zpy8fn9ttvtrqgzvw1vtejoz6.xz"

    maintainers("jcphill")

    # Box's "shared/static" links are stable, permanent redirects to the
    # current backing file (this is the same URL Cardinal's own
    # scripts/download-openmc-cross-sections.sh uses directly with curl -L),
    # so there is no better long-term URL to pin against. The archive
    # extracts to a top-level endfb-vii.1-hdf5/ directory containing
    # cross_sections.xml plus the per-nuclide/per-element HDF5 data.
    # Box's URL basename has no .tar.xz/.txz suffix for Spack's archive-type
    # sniffing to key off, so it would otherwise be (mis)treated as a single
    # xz-compressed file rather than a tar archive; `extension` forces the
    # correct tar.xz handling regardless of the URL's basename.
    version(
        "vii.1",
        sha256="5bc4b62a602d569e3a801c3499f03378192e83623c3eb39500804178706781f9",
        extension="tar.xz",
    )

    def url_for_version(self, version):
        return self.url

    def install(self, spec, prefix):
        install_tree(self.stage.source_path, prefix)

    def setup_dependent_run_environment(self, env, dependent_spec):
        env.set("OPENMC_CROSS_SECTIONS", join_path(self.prefix, "cross_sections.xml"))

    def setup_run_environment(self, env):
        env.set("OPENMC_CROSS_SECTIONS", join_path(self.prefix, "cross_sections.xml"))
