NIST_XLSX_URL := https://csrc.nist.gov/files/pubs/sp/800/171/r2/upd1/final/docs/sp800-171r2-security-reqs.xlsx
NIST_XLSX := data/sp800-171r2-security-reqs.xlsx
CONTROLS_JSON := controls.json
PRICING_JSON := pricing.json

.PHONY: controls pricing clean setup-db seed

controls: $(CONTROLS_JSON)

# Always refetch, and replace pricing.json only when the fetch succeeds.
pricing:
	python3 scripts/fetch-pricing.py > $(PRICING_JSON).new
	mv $(PRICING_JSON).new $(PRICING_JSON)
	@echo "Wrote pricing to $(PRICING_JSON)"

setup-db:
	psql "$(COMMIT2CONTROL_DB)" -c "CREATE EXTENSION IF NOT EXISTS vector;"
	@echo "pgvector extension enabled"

seed: controls setup-db
	python3 commit-to-control --seed

$(CONTROLS_JSON): $(NIST_XLSX)
	python3 scripts/extract-controls.py $< > $@
	@echo "Wrote $$(python3 -c "import json; print(len(json.load(open('$@'))))" ) controls to $@"

$(NIST_XLSX):
	mkdir -p data
	curl -sL "$(NIST_XLSX_URL)" -o $@

clean:
	rm -f $(CONTROLS_JSON) $(NIST_XLSX)
	rmdir data 2>/dev/null || true
