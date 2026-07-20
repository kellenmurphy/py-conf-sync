CURRENT_VERSION := $(shell grep -m1 '__version__' py_conf_sync.py | cut -d'"' -f2)
MAJOR := $(word 1,$(subst ., ,$(CURRENT_VERSION)))
MINOR := $(word 2,$(subst ., ,$(CURRENT_VERSION)))
PATCH := $(word 3,$(subst ., ,$(CURRENT_VERSION)))

.DEFAULT_GOAL := help

.PHONY: help patch minor major release-finish

help:
	@echo "Usage: make [patch|minor|major]   — open a version-bump release PR"
	@echo "       make release-finish        — after the PR merges: tag + GitHub release"
	@echo "  Current version: $(CURRENT_VERSION)"

patch:
	$(eval NEW_VERSION := $(MAJOR).$(MINOR).$(shell echo $$(($(PATCH)+1))))
	$(call _start_release,$(NEW_VERSION))

minor:
	$(eval NEW_VERSION := $(MAJOR).$(shell echo $$(($(MINOR)+1))).0)
	$(call _start_release,$(NEW_VERSION))

major:
	$(eval NEW_VERSION := $(shell echo $$(($(MAJOR)+1))).0.0)
	$(call _start_release,$(NEW_VERSION))

# Main is protected (PRs + status checks + signed commits required), so a
# release happens in two phases: a version-bump PR, then — after merge —
# tagging the merge commit and publishing the GitHub release.
define _start_release
	@git diff --quiet && git diff --cached --quiet || { echo "[error] working tree not clean"; exit 1; }
	git fetch origin
	git switch -c release-$(1) origin/main
	sed -i.bak 's/__version__ = "$(CURRENT_VERSION)"/__version__ = "$(1)"/' py_conf_sync.py && rm py_conf_sync.py.bak
	git add py_conf_sync.py
	git commit -m "chore: bump version to $(1)"
	git push -u origin release-$(1)
	gh pr create --title "chore: bump version to $(1)" --body "Release v$(1). After merging, run \`make release-finish\` to tag and publish."
	@echo "Release PR opened. After it merges: make release-finish"
endef

release-finish:
	git switch main
	git pull --ff-only
	@V=$$(grep -m1 '__version__' py_conf_sync.py | cut -d'"' -f2); \
	if git rev-parse "v$$V" >/dev/null 2>&1; then echo "[error] tag v$$V already exists"; exit 1; fi; \
	git tag -m "v$$V" "v$$V" && \
	git push origin "v$$V" && \
	gh release create "v$$V" --title "v$$V" --generate-notes && \
	echo "Released v$$V"
