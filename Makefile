VERSION=$(shell dpkg-parsechangelog | grep Version: | cut -d " " -f 2)

default: check

.PHONY: build

build:
	./setup.py build_ext -i

check:: testsuite tag-status ruff

FIXERS = $(patsubst fixers/%.sh,%,$(wildcard fixers/*.sh)) $(patsubst fixers/%.py,%,$(wildcard fixers/*.py))

$(patsubst %,check-fixer-%,$(FIXERS)): check-fixer-%:
	PYTHONPATH=$(PWD):$(PYTHONPATH) python3 -m lintian_brush.tests.fixers --fixer=$*

.PHONY: ruff testsuite unsupported

ruff::
	ruff check .

typing:: build
	mypy lintian_brush fixers

tag-status::
	python3 tag-status.py --check

testsuite:: build
	python3 -m unittest lintian_brush.tests.test_suite

testsuite-core: build
	python3 -m unittest lintian_brush.tests.core_test_suite

README.md::
	PYTHONPATH=$(PWD):$(PYTHONPATH) ./buildtools/update-readme.py

lintian-tags:
	lintian-explain-tags --list-tags > lintian-tags

.PHONY: lintian-tags lintian-brush-tags

lintian-brush-tags:
	PYTHONPATH=$(PWD):$(PYTHONPATH) python3 -m lintian_brush --list-tags 2> lintian-brush-tags

unsupported: lintian-tags lintian-brush-tags
	awk 'NR==FNR{a[$$0]=1;next}!a[$$0]' lintian-brush-tags lintian-tags

update-readme:
	brz diff README.md
	$(MAKE) README.md
	brz diff README.md || brz commit -m "Update list of fixers in README.md" README.md

release: check update-readme
	./setup.py sdist
	twine upload --sign dist/lintian-brush-$(VERSION).tar.gz

update-spdx:
	python3 download-license-data.py > spdx.json
	brz diff spdx.json || brz commit -m "Update SPDX license data" spdx.json

update-key-package-versions:
	python3 key-package-versions.py
	brz diff key-package-versions.json || brz commit -m "Update key package versions" key-package-versions.json

update-renamed-tags:
	python3 renamed-tags.py
	brz diff renamed-tags.json || brz commit -m "Update renamed tags" renamed-tags.json

update: update-spdx update-readme update-renamed-tags update-key-package-versions

next:
	python3 next.py

docker:
	buildah build -t ghcr.io/jelmer/lintian-brush:latest Dockerfile.lintian-brush .
	buildah push ghcr.io/jelmer/lintian-brush:latest
	buildah build -t ghcr.io/jelmer/deb-scrub-obsolete:latest Dockerfile.deb-scrub-obsolete .
	buildah push ghcr.io/jelmer/deb-scrub-obsolete:latest
	buildah build -t ghcr.io/jelmer/debianize:latest Dockerfile.debianize .
	buildah push ghcr.io/jelmer/debianize:latest
	buildah build -t ghcr.io/jelmer/debianize:latest Dockerfile.debianize .
	buildah push ghcr.io/jelmer/debianize:latest

