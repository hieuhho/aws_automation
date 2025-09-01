# ---- config ----
IMAGE = s3cli:dev
AWS_DIR = $(HOME)/.aws
PROFILE = default
REGION = us-east-1
LAST_BUCKET_FILE = .last_bucket

# ---- targets ----

.PHONY: build create destroy last shell

build:
	docker build -t $(IMAGE) .

create:
	@echo "➡️  creating bucket..."
	@docker run --rm -i \
		-v $(AWS_DIR):/home/app/.aws:ro \
		-e AWS_PROFILE=$(PROFILE) \
		-e AWS_REGION=$(REGION) \
		$(IMAGE) python buckets.py create --region $(REGION) | tee $(LAST_BUCKET_FILE)
	@echo "✅ bucket saved to $(LAST_BUCKET_FILE)"

destroy:
	@if [ -z "$(BUCKET)" ] && [ ! -f $(LAST_BUCKET_FILE) ]; then \
		echo "❌ No BUCKET specified and no $(LAST_BUCKET_FILE) found."; \
		echo "   Usage: make destroy BUCKET=<bucket-name>"; \
		exit 1; \
	fi
	@bucket=$${BUCKET:-$$(cat $(LAST_BUCKET_FILE))}; \
	echo "➡️  destroying bucket $$bucket..."; \
	docker run --rm -i \
		-v $(AWS_DIR):/home/app/.aws:ro \
		-e AWS_PROFILE=$(PROFILE) \
		-e AWS_REGION=$(REGION) \
		$(IMAGE) python buckets.py destroy --name $$bucket --region $(REGION); \
	echo "🗑️  destroyed: $$bucket"

last:
	@if [ -f $(LAST_BUCKET_FILE) ]; then \
		echo "📦 last bucket: $$(cat $(LAST_BUCKET_FILE))"; \
	else \
		echo "❌ No last bucket recorded."; \
	fi

shell:
	docker run --rm -it \
		-v $(AWS_DIR):/home/app/.aws:ro \
		-e AWS_PROFILE=$(PROFILE) \
		-e AWS_REGION=$(REGION) \
		$(IMAGE) bash
