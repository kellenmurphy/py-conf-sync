CURRENT_VERSION := $(shell grep -m1 '__version__' py_conf_sync.py | cut -d'"' -f2)
MAJOR := $(word 1,$(subst ., ,$(CURRENT_VERSION)))
MINOR := $(word 2,$(subst ., ,$(CURRENT_VERSION)))
PATCH := $(word 3,$(subst ., ,$(CURRENT_VERSION)))

.DEFAULT_GOAL := help

.PHONY: help patch minor major

help:
	@echo "Usage: make [patch|minor|major]"
	@echo "  Current version: $(CURRENT_VERSION)"

patch:
	$(eval NEW_VERSION := $(MAJOR).$(MINOR).$(shell echo $$(($(PATCH)+1))))
	$(call _release,$(NEW_VERSION))

minor:
	$(eval NEW_VERSION := $(MAJOR).$(shell echo $$(($(MINOR)+1))).0)
	$(call _release,$(NEW_VERSION))

major:
	$(eval NEW_VERSION := $(shell echo $$(($(MAJOR)+1))).0.0)
	$(call _release,$(NEW_VERSION))

define _release
	sed -i 's/__version__ = "$(CURRENT_VERSION)"/__version__ = "$(1)"/' py_conf_sync.py
	git add py_conf_sync.py
	git commit -m "chore: bump version to $(1)"
	git tag v$(1)
	git push origin main --tags
endef
