lintian-brush
=============

This package contains a set of scripts to automatically fix some common issues in
Debian packages.

Running lintian-brush
---------------------

Simply run::

```shell
lintian-brush
```

in the top-level of your (version controlled) Debian package.

.. _supported-tags:

Supported tags
--------------

The current set of lintian tags for which a fixer is available that can fix a
subset of the issues:

* adopted-extended-field
* ancient-python-version-field
* ancient-standards-version
* autotools-pkg-config-macro-not-cross-compilation-safe
* build-depends-on-build-essential
* build-depends-on-obsolete-package
* built-using-field-on-arch-all-package
* carriage-return-line-feed
* comma-separated-files-in-dep5-copyright
* copyright-does-not-refer-to-common-license-file
* copyright-file-contains-full-apache-2-license
* copyright-file-contains-full-gfdl-license
* copyright-file-contains-full-gpl-license
* copyright-has-crs
* copyright-not-using-common-license-for-apache2
* copyright-not-using-common-license-for-gfdl
* copyright-not-using-common-license-for-gpl
* copyright-not-using-common-license-for-lgpl
* copyright-refers-to-symlink-license
* copyright-refers-to-versionless-license-file
* custom-compression-in-debian-source-options
* cute-field
* debhelper-but-no-misc-depends
* debhelper-tools-from-autotools-dev-are-deprecated
* debian-changelog-file-contains-obsolete-user-emacs-settings
* debian-changelog-has-wrong-day-of-week
* debian-changelog-line-too-long
* debian-control-has-empty-field
* debian-control-has-obsolete-dbg-package
* debian-control-has-unusual-field-spacing
* debian-pycompat-is-obsolete
* debian-pyversions-is-obsolete
* debian-rules-calls-pwd
* debian-rules-contains-unnecessary-get-orig-source-target
* debian-rules-missing-recommended-target
* debian-rules-not-executable
* debian-rules-parses-dpkg-parsechangelog
* debian-rules-sets-dpkg-architecture-variable
* debian-rules-uses-as-needed-linker-flag
* debian-rules-uses-special-shell-variable
* debian-rules-uses-unnecessary-dh-argument
* debian-tests-control-and-control-autodep8
* debian-tests-control-autodep8-is-obsolete
* debian-upstream-obsolete-path
* debian-watch-contains-dh_make-template
* debian-watch-does-not-check-openpgp-signature
* debian-watch-file-is-missing
* debian-watch-file-pubkey-file-is-missing
* debian-watch-file-uses-deprecated-githubredir
* debian-watch-uses-insecure-uri
* debug-symbol-migration-possibly-complete
* declares-possibly-conflicting-debhelper-compat-versions
* dep3-format-patch-author-or-from-is-better
* dep5-file-paragraph-references-header-paragraph
* desktop-entry-contains-encoding-key
* desktop-entry-file-has-crs
* dh-clean-k-is-deprecated
* dh-quilt-addon-but-quilt-source-format
* dm-upload-allowed-is-obsolete
* empty-debian-tests-control
* excessive-priority-for-library-package
* executable-desktop-file
* extended-description-contains-empty-paragraph
* extended-description-is-empty
* faulty-debian-qa-group-phrase
* field-name-typo-in-dep5-copyright
* font-package-not-multi-arch-foreign
* global-files-wildcard-not-first-paragraph-in-dep5-copyright
* homepage-field-uses-insecure-uri
* homepage-in-binary-package
* initial-upload-closes-no-bugs
* insecure-copyright-format-uri
* installable-field-mirrors-source
* invalid-short-name-in-dep5-copyright
* invalid-standards-version
* libmodule-build-perl-needs-to-be-in-build-depends
* license-file-listed-in-debian-copyright
* maintainer-also-in-uploaders
* maintainer-script-empty
* maintainer-script-without-set-e
* malformed-dm-upload-allowed
* malformed-override
* mismatched-override
* missing-build-dependency-for-dh-addon
* missing-build-dependency-for-dh_-command
* missing-built-using-field-for-golang-package
* missing-debian-source-format
* missing-prerequisite-for-pyproject-backend
* missing-vcs-browser-field
* misspelled-closes-bug
* new-package-uses-date-based-version-number
* no-copyright-file
* no-homepage-field
* no-versioned-debhelper-prerequisite
* obsolete-debian-watch-file-standard
* obsolete-field-in-dep5-copyright
* obsolete-runtime-tests-restriction
* obsolete-url-in-packaging
* obsolete-vim-addon-manager
* old-dpmt-vcs
* old-fsf-address-in-copyright-file
* old-papt-vcs
* old-source-override-location
* older-debian-watch-file-standard
* older-source-format
* out-of-date-copyright-format-uri
* out-of-date-standards-version
* package-contains-linda-override
* package-uses-deprecated-debhelper-compat-version
* package-uses-old-debhelper-compat-version
* patch-file-present-but-not-mentioned-in-series
* pkg-js-tools-test-is-missing
* possible-missing-colon-in-closes
* priority-extra-is-replaced-by-priority-optional
* public-upstream-key-in-native-package
* public-upstream-key-not-minimal
* public-upstream-keys-in-multiple-locations
* pypi-homepage
* python-teams-merged
* quilt-series-but-no-build-dep
* quilt-series-without-trailing-newline
* recommended-field
* renamed-tag
* required-field
* rubygem-homepage
* silent-on-rules-requiring-root
* space-in-std-shortname-in-dep5-copyright
* systemd-service-alias-without-extension
* systemd-service-file-refers-to-obsolete-bindto
* systemd-service-file-refers-to-obsolete-target
* systemd-service-file-refers-to-var-run
* systemd-service-file-shutdown-problems
* tab-in-license-text
* team/pkg-perl/testsuite/no-testsuite-header
* team/pkg-perl/vcs/no-git
* team/pkg-perl/vcs/no-team-url
* trailing-whitespace
* transitional-package-not-oldlibs-optional
* typo-in-debhelper-override-target
* unnecessary-team-upload
* unnecessary-testsuite-autopkgtest-field
* unused-build-dependency-on-cdbs
* unused-license-paragraph-in-dep5-copyright
* unused-override
* unversioned-copyright-format-uri
* uploaders-in-orphan
* upstream-metadata-file-is-missing
* upstream-metadata-in-native-source
* upstream-metadata-missing-bug-tracking
* upstream-metadata-missing-repository
* upstream-metadata-not-yaml-mapping
* upstream-metadata-yaml-invalid
* useless-autoreconf-build-depends
* uses-debhelper-compat-file
* uses-deprecated-adttmp
* vcs-field-bitrotted
* vcs-field-mismatch
* vcs-field-not-canonical
* vcs-field-uses-insecure-uri
* vcs-field-uses-not-recommended-uri-format
* vcs-obsolete-in-debian-infrastructure
* wrong-section-according-to-package-name

.. _writing-fixers:

Writing new fixers
------------------

For a more extensive write-up, see the
[guide on writing fixers](doc/fixer-writing-guide.rst).

Ideally, fixers target a particular set of lintian tags. This is not strictly
required, but makes it possible to easily find all packages that a particular
fixer can be used on.

Each fixer is a simple script that lives under ``fixers``. Scripts should
be registered in the ``index.desc`` file in the same directory.

A fixer is run in the root directory of a package, where it can make changes
it deems necessary. If a fixer can not provide any improvements, it can simply
leave the working tree untouched - lintian-brush will not create any commits for it
or update the changelog. If exits with a non-zero return code, whatever changes
it has made will be discarded and the fixer will be reported as having failed.

The following additional environment variables are set:

 * ``DEB_SOURCE``: The name of the source package that is being edited.
 * ``CURRENT_VERSION``: Package version that is being edited.
 * ``COMPAT_RELEASE``: Debian release to be compatible with. Usually ``sid``
   when --modern was specified and the name of the current stable release otherwise.
 * ``NET_ACCESS``: Whether the fixer is allowed to make network connections
   (e.g. sending HTTP requests). Used by --disable-net-access and the testsuite.
   Set to either ``allow`` or ``disallow``.
 * ``OPINIONATED``: Set to ``yes`` or ``no``. If ``no``, fixers are not expected
   to make changes in which there is no obvious single correct fix.

For fixer written in python, the ``lintian_brush.fixer`` module can be used for
convenient access to these variables.

A fixer should write a short description of the changes it has made to standard
out; this will be used for the commit message.

It can include optional metadata in its output::

 * ``Fixed-Lintian-Tags:`` followed by a comma-separated list of lintian tags
   that it claims to have fixed. This will make lintian-brush include
   links to documentation about the fixed lintian tags. In the future,
   it may also support building the package to verify the lintian tag
   is actually resolved.

 * ``Certainty:`` followed by ``certain``, ``confident``, ``likely`` or
   ``possible``, indicating how certain the fixer is that the fix was the right
   one.

The default minimum certainty level is "certain"; any incorrect change made
with certainty "certain" is considered *at least* a normal-severity bug.

The easiest way to test fixers is to create a skeleton *in* and *out* source
tree under ``tests/FIXER-NAME/TEST-NAME``. The ``in`` directory should contain
the tree to run the fixer on, and ``out`` contains the directory after it has
run. It's fine to create directories with only one or two control files, if the
fixer only needs those. To run the tests for a single fixer, you can use "make
check-fixer-$NAME".

GitHub Action
-------------

If you're hosting a Git repository on GitHub, you can use the [lintian-brush
GitHub action](https://github.com/gizmoguy/action-lintian-brush) to
automatically run lintian-brush.
