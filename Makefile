# Короткие команды skills-kit. POSIX make: первый таргет — цель по умолчанию.
# Запуск без аргументов печатает справку; тяжёлых и «магических» целей нет.

PYTHON ?= python3

help:
	@echo "skills-kit: короткие команды"
	@echo ""
	@echo "  make check        check.py + lang_check.py"
	@echo "  make test         тесты валидатора, поиска и роутинг-эвала"
	@echo "  make hooks        локальный git-хук: git config core.hooksPath .githooks"
	@echo "  make find Q=…     поиск навыка по фразе"
	@echo "  make packs        цели установки и группы навыков"
	@echo "  make verify TARGET=claude  проверка установки: навык виден в хосте"
	@echo "  make install-dry  install.sh --target all --dry-run"
	@echo "  make pack         dist/ плоской раскладкой: skills/<имя>/SKILL.md"
	@echo "  make release      dist/ + релизный zip (версия из plugin.json)"

check:
	@./scripts/check.py
	@./scripts/lang_check.py

test:
	@$(PYTHON) ./scripts/test_check.py
	@if [ -f ./scripts/test_routing_eval.py ]; then \
		$(PYTHON) ./scripts/test_routing_eval.py; \
	else \
		echo "scripts/test_routing_eval.py нет — пропущено"; \
	fi
	@if [ -f ./scripts/test_find_skill.py ]; then \
		$(PYTHON) ./scripts/test_find_skill.py; \
	else \
		echo "scripts/test_find_skill.py нет — пропущено"; \
	fi
	@if [ -f ./scripts/test_verify_install.py ]; then \
		$(PYTHON) ./scripts/test_verify_install.py; \
	else \
		echo "scripts/test_verify_install.py нет — пропущено"; \
	fi

find:
	@if [ -z "$(Q)" ]; then echo 'укажи фразу: make find Q="готово, можно коммитить?"'; exit 2; fi
	@$(PYTHON) ./scripts/find_skill.py "$(Q)"

packs:
	@./scripts/install.sh --target list

verify:
	@if [ -z "$(TARGET)" ]; then echo 'укажи цель: make verify TARGET=claude'; exit 2; fi
	@$(PYTHON) ./scripts/verify_install.py --target "$(TARGET)"

hooks:
	@chmod +x .githooks/pre-commit
	@git config core.hooksPath .githooks
	@echo "хук установлен: git config core.hooksPath .githooks"

install-dry:
	@./scripts/install.sh --target all --dry-run

pack:
	@$(PYTHON) ./scripts/pack.py --clean

release:
	@$(PYTHON) ./scripts/pack.py --release

.PHONY: help check test hooks find packs verify install-dry pack release
