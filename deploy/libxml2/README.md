# Local libxml2 security backport

This is a local Alpine2.13.9-r3 recipe, not an official Alpine release. It preserves
the upstream2.13.9 ABI and both existing Alpine patches, adding GNOME commit
d1686f91dbda141a752200419d35639fd6b38340 for CVE-2026-86140. Original source/patch
checksums remain in APKBUILD; source provenance is in the V4.1 evidence manifest.

The build runs upstream `make runtests`, then a canary/bounds regression compiled
from the actual static function in patched valid.c. Reversing the upstream fix must
make that same regression abort with exit134; otherwise the build fails. Optional
external W3C/XSTC corpora are absent and are not counted as executed checks.

The final database image receives only the built runtime package, not the compiler,
signing key or build tools. It preserves PostgreSQL16 and SQL/XML. The Dockerfile
checks that the upgraded base still has libxml2=2.13.9-r2 before applying the local
package. If that changes, review/rebase the patch recipe and dependency advisories;
do not bypass the guard or silently replace a newer distro security package.

A destination-architecture image scan plus XML, populated-volume restart and
backup/restore tests are required. Prefer a verified fixed official compatible
package once available, then remove this local maintenance obligation after tests.
