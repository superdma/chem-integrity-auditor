#!/usr/bin/env bash
# Pre-change smoke test for chem-integrity-auditor.
#
# Checks: every script compiles and answers --help; every deterministic check
# fires on a positive fixture and stays silent on a negative one; offline
# PubChem cache works. Runs in ~20 s, no network required.
#
#   bash tests/smoketest.sh
#
# Exits non-zero on any failure.

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$ROOT/scripts"
FIX="$ROOT/tests/fixtures"
TMP="$(mktemp -d)"
MOCK_PID=""
trap 'test -n "$MOCK_PID" && kill "$MOCK_PID" 2>/dev/null; rm -rf "$TMP"' EXIT

PASS=0
FAIL=0
ok()  { echo "  PASS  $1"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL  $1"; FAIL=$((FAIL + 1)); }

run_ok() {  # run_ok <label> <command...>
  local label="$1"; shift
  if "$@" >"$TMP/out.log" 2>&1; then ok "$label"; else
    bad "$label"; tail -8 "$TMP/out.log" | sed 's/^/        /'
  fi
}

echo "== 0. fixtures =="
if [ ! -f "$FIX/numeric/full.md" ] || [ ! -f "$FIX/spectra/segment_dup.png" ] || [ ! -f "$FIX/calibration/manifest.json" ]; then
  run_ok "generate fixtures" python3 "$ROOT/tests/make_fixtures.py"
fi

echo
echo "== 1. compile =="
for f in "$SCRIPTS"/*.py; do
  if python3 -m py_compile "$f" >/dev/null 2>&1; then
    ok "compile $(basename "$f")"
  else
    bad "compile $(basename "$f")"
  fi
done

echo
echo "== 2. --help =="
for f in "$SCRIPTS"/*.py; do
  if python3 "$f" --help >/dev/null 2>&1; then
    ok "--help $(basename "$f")"
  else
    bad "--help $(basename "$f")"
  fi
done

echo
echo "== 3. chem_numeric: positive control =="
if python3 "$SCRIPTS/chem_numeric.py" "$FIX/numeric" \
     --output "$TMP/chem.json" >/dev/null 2>&1; then
  if python3 - "$TMP/chem.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
checks = {f["check"] for f in d["findings"]}
hard = [f for f in d["findings"] if f["severity"] == "hard"]
assert "yield_roundness" in checks, checks
assert "chn_elemental" in checks, checks
assert "hrms_mw" in checks, checks
assert len(hard) >= 2, hard
PY
  then ok "yield/CHN/HRMS leads fire"; else bad "yield/CHN/HRMS leads missing"; fi
else
  bad "chem_numeric positive run"
fi

echo
echo "== 4. chem_numeric: negative control =="
if python3 "$SCRIPTS/chem_numeric.py" "$FIX/numeric_clean" \
     --output "$TMP/clean.json" >/dev/null 2>&1; then
  if python3 - "$TMP/clean.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["findings_count"] == 0, d["findings"]
PY
  then ok "clean table produces 0 findings"; else bad "clean table produced findings"; fi
else
  bad "chem_numeric negative run"
fi

echo
echo "== 5. numeric_forensics =="
if python3 "$SCRIPTS/numeric_forensics.py" "$FIX/numeric" \
     --output "$TMP/nf.json" >/dev/null 2>&1; then
  if python3 - "$TMP/nf.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert isinstance(d, dict) and d, "empty report"
PY
  then ok "numeric_forensics writes a report"; else bad "numeric_forensics report invalid"; fi
else
  bad "numeric_forensics run"
fi

echo
echo "== 6. evidence ledger =="
if python3 "$SCRIPTS/build_evidence_ledger.py" "$FIX/numeric" \
     --output "$TMP/ledger.json" >/dev/null 2>&1; then
  if python3 - "$TMP/ledger.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["schema_version"] == "1.0"
assert isinstance(d["ledger_items"], list) and len(d["ledger_items"]) > 10
assert d["stats"]["ledger_items"] == len(d["ledger_items"])
assert d["stats"]["tables"] >= 3, d["stats"]
assert d["stats"]["cells"] > 0, d["stats"]
PY
  then ok "ledger indexes the fixture"; else bad "ledger output invalid"; fi
else
  bad "build_evidence_ledger run"
fi

echo
echo "== 7. structure_check: offline positive =="
if python3 "$SCRIPTS/structure_check.py" --name aspirin \
     --reported-formula C9H8O4 --reported-mw 180.16 \
     --reported-chn "C=60.02,H=4.51" --reported-chn-calcd "C=60.00,H=4.48" \
     --reported-mz "181.0495 [M+H]+" \
     --offline --cache "$FIX/pubchem_cache" \
     --output "$TMP/sc.json" >/dev/null 2>&1; then
  if python3 - "$TMP/sc.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["summary"]["hard"] == 0, d["summary"]
checks = {c["check"]: c for c in d["queries"][0]["comparisons"]}
assert checks["formula"]["severity"] == "pass"
assert checks["mw"]["severity"] == "pass"
assert checks["hrms"]["severity"] == "pass"
PY
  then ok "aspirin identity agrees"; else bad "aspirin identity checks failed"; fi
else
  bad "structure_check offline positive run"
fi

echo
echo "== 8. structure_check: offline negative =="
if python3 "$SCRIPTS/structure_check.py" --name aspirin \
     --reported-formula C9H8O5 --reported-mw 196.16 \
     --offline --cache "$FIX/pubchem_cache" \
     --output "$TMP/sc_bad.json" >/dev/null 2>&1; then
  if python3 - "$TMP/sc_bad.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
checks = {c["check"]: c for c in d["queries"][0]["comparisons"]}
assert checks["formula"]["severity"] == "hard", checks["formula"]
assert checks["mw"]["severity"] == "soft", checks["mw"]
PY
  then ok "wrong formula/MW are flagged"; else bad "wrong formula/MW not flagged"; fi
else
  bad "structure_check offline negative run"
fi

echo
echo "== 8b. structure_check: batch mode =="
cat > "$TMP/compounds.json" <<'JSON'
[{"label":"aspirin","name":"aspirin","reported_formula":"C9H8O4"},
 {"label":"caffeine","name":"caffeine","reported_formula":"C8H10N4O2"}]
JSON
python3 "$SCRIPTS/structure_check.py" --batch "$TMP/compounds.json" \
    --offline --cache "$FIX/pubchem_cache" --output "$TMP/batch.json" \
    >/dev/null 2>&1
python3 - "$TMP/batch.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["summary"]["n_compounds"] == 2, d["summary"]
labels = [q["label"] for q in d["queries"]]
assert labels == ["aspirin", "caffeine"], labels
PY
if [ $? -eq 0 ]; then ok "batch mode reads exactly the supplied compounds"
else bad "batch mode added a phantom compound"; fi

echo
echo "== 9. reference_spectrum_match: image + reference =="
if python3 "$SCRIPTS/reference_spectrum_match.py" \
     --sample-image "$FIX/spectra/spec_a.png" \
     --sample-x0 "100:8.0" --sample-x1 "700:0.0" --technique h1nmr \
     --ref "$FIX/refs/ref.csv" --ref "$FIX/refs/ref_other.csv" \
     --output "$TMP/rm.json" >/dev/null 2>&1; then
  if python3 - "$TMP/rm.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
by = {r["label"]: r["match"] for r in d["references"] if "match" in r}
assert len(d["sample"]["peaks"]) == 4, d["sample"]["peaks"]
assert by["ref"]["score"] == 1.0, by["ref"]
assert by["ref"]["verdict"] == "very_high", by["ref"]
assert by["ref_other"]["score"] < 0.55, by["ref_other"]
PY
  then ok "digitized spectrum matches its reference, not the other"; else bad "reference match scoring wrong"; fi
else
  bad "reference_spectrum_match image run"
fi

echo
echo "== 10. reference_spectrum_match: text/peak-table mode =="
if python3 "$SCRIPTS/reference_spectrum_match.py" \
     --sample-peaks "$FIX/refs/sample_peaks.txt" --technique h1nmr \
     --ref "$FIX/refs/ref_sdbs.txt" --ref-format text \
     --output "$TMP/rm_txt.json" >/dev/null 2>&1; then
  if python3 - "$TMP/rm_txt.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
m = d["best"]["match"]
assert m["score"] == 1.0 and m["verdict"] == "very_high", m
PY
  then ok "SDBS-style peak table parses and matches"; else bad "text peak table failed"; fi
else
  bad "reference_spectrum_match text run"
fi

echo
echo "== 11. image_dup =="
python3 "$SCRIPTS/image_dup.py" "$FIX/images/dup_a.png" \
    "$FIX/images/dup_b.png" "$FIX/images/diff.png" >"$TMP/dup.log" 2>&1
if grep -Eq 'dup_a\.png +dup_b\.png.*strong duplicate' "$TMP/dup.log"; then
  ok "brightness-shifted copy is a strong duplicate"
else
  bad "brightness-shifted copy missed"
  tail -5 "$TMP/dup.log" | sed 's/^/        /'
fi
if grep -Eq 'dup_a\.png +diff\.png.*strong duplicate' "$TMP/dup.log"; then
  bad "unrelated image falsely flagged"
else
  ok "unrelated image not flagged"
fi

echo
echo "== 12. spectral_noise_fingerprint =="
python3 "$SCRIPTS/spectral_noise_fingerprint.py" \
    "$FIX/spectra/spec_a.png" "$FIX/spectra/spec_b.png" \
    --out "$TMP/fp_same.json" >/dev/null 2>&1
python3 "$SCRIPTS/spectral_noise_fingerprint.py" \
    "$FIX/spectra/spec_a.png" "$FIX/spectra/spec_c.png" \
    --out "$TMP/fp_diff.json" >/dev/null 2>&1
if python3 - "$TMP" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
same = json.load(open(p / "fp_same.json"))
diff = json.load(open(p / "fp_diff.json"))
assert same["applicable"] is True
assert same["curve_r"] >= 0.85, same["curve_r"]
assert diff["curve_r"] < 0.85, diff["curve_r"]
PY
then ok "same-compound pair correlates, unrelated pair does not"
else bad "spectral fingerprint thresholds wrong"; fi

echo
echo "== 13. panel_split =="
mkdir -p "$TMP/panels"
python3 "$SCRIPTS/panel_split.py" "$FIX/panels/figure_2panel.png" \
    "$TMP/panels" >"$TMP/ps.log" 2>&1
N=$(find "$TMP/panels" -name '*.png' | wc -l)
if [ "$N" -ge 2 ]; then ok "2-panel figure split into $N panels"
else bad "panel_split produced $N panels"; cat "$TMP/ps.log" | sed 's/^/        /'; fi

echo
echo "== 14. stack_split =="
mkdir -p "$TMP/bands"
python3 "$SCRIPTS/stack_split.py" "$FIX/panels/stacked_3band.png" \
    "$TMP/bands" --keep-color auto >"$TMP/ss.log" 2>&1
N=$(find "$TMP/bands" -name '*.png' | wc -l)
if [ "$N" -eq 3 ]; then ok "3 stacked traces split into 3 bands"
else bad "stack_split produced $N bands"; cat "$TMP/ss.log" | sed 's/^/        /'; fi
if grep -q 'colour=red' "$TMP/ss.log" && grep -q 'colour=blue' "$TMP/ss.log"; then
  ok "auto colour isolation identifies traces"
else bad "auto colour isolation failed"; fi

echo
echo "== 15. MinerU local v1 (mock) =="
MOCK_PORT=$(python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)
python3 "$ROOT/tests/mock_mineru.py" "$MOCK_PORT" >"$TMP/mock.log" 2>&1 &
MOCK_PID=$!
for _ in $(seq 1 50); do
  curl -sS -m 1 "http://127.0.0.1:$MOCK_PORT/v1/health" >/dev/null 2>&1 && break
  sleep 0.1
done
python3 "$SCRIPTS/mineru_convert.py" "$FIX/mineru/mock.pdf" \
    --output "$TMP/mu_v1" --backend-mode local --local-api v1 \
    --base-url "http://127.0.0.1:$MOCK_PORT" --tier flash \
    --interval 1 --timeout 20 >"$TMP/mu_v1.log" 2>&1
if [ -f "$TMP/mu_v1/full.md" ] && grep -q "Mock MinerU output" "$TMP/mu_v1/full.md"; then
  ok "local v1 create/upload/poll/unzip produces full.md"
else
  bad "local v1 flow failed"; tail -8 "$TMP/mu_v1.log" | sed 's/^/        /'
fi

echo
echo "== 16. MinerU local legacy /file_parse (mock) =="
python3 "$SCRIPTS/mineru_convert.py" "$FIX/mineru/mock.pdf" \
    --output "$TMP/mu_legacy" --backend-mode local --local-api legacy \
    --base-url "http://127.0.0.1:$MOCK_PORT" \
    --timeout 20 >"$TMP/mu_legacy.log" 2>&1
if [ -f "$TMP/mu_legacy/full.md" ] && grep -q "Mock MinerU output" "$TMP/mu_legacy/full.md"; then
  ok "legacy /file_parse path produces full.md"
else
  bad "legacy local flow failed"; tail -8 "$TMP/mu_legacy.log" | sed 's/^/        /'
fi

echo
echo "== 17. MinerU official cloud v4 (mock) =="
MINERU_API_BASE="http://127.0.0.1:$MOCK_PORT" MINERU_API_TOKEN="test-token" \
python3 "$SCRIPTS/mineru_convert.py" "$FIX/mineru/mock.pdf" \
    --output "$TMP/mu_cloud" --backend-mode cloud \
    --interval 1 --timeout 20 >"$TMP/mu_cloud.log" 2>&1
if [ -f "$TMP/mu_cloud/full.md" ] && grep -q "Mock MinerU output" "$TMP/mu_cloud/full.md"; then
  ok "cloud batch upload/poll/zip produces full.md"
else
  bad "cloud flow failed"; tail -8 "$TMP/mu_cloud.log" | sed 's/^/        /'
fi

echo
echo "== 18. MinerU auto fallback local→cloud (mock) =="
MINERU_API_BASE="http://127.0.0.1:$MOCK_PORT" MINERU_API_TOKEN="test-token" \
python3 "$SCRIPTS/mineru_convert.py" "$FIX/mineru/mock.pdf" \
    --output "$TMP/mu_auto" --backend-mode auto \
    --base-url "http://127.0.0.1:9" \
    --interval 1 --timeout 20 >"$TMP/mu_auto.log" 2>&1
if [ -f "$TMP/mu_auto/full.md" ] && \
   python3 - "$TMP/mu_auto/mineru_manifest.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert "cloud" in d.get("source", ""), d.get("source")
PY
then ok "auto falls back from dead local to cloud"
else bad "auto fallback failed"; tail -10 "$TMP/mu_auto.log" | sed 's/^/        /'; fi

echo
echo "== 19. MinerU probe =="
if python3 "$SCRIPTS/mineru_convert.py" --probe \
     --base-url "http://127.0.0.1:$MOCK_PORT" >"$TMP/probe.log" 2>&1; then
  ok "--probe reports the mock local server"
else bad "--probe failed"; cat "$TMP/probe.log" | sed 's/^/        /'; fi

echo
echo "== 20. spectral_segment_dup =="
python3 "$SCRIPTS/spectral_segment_dup.py" \
    --image "$FIX/spectra/segment_dup.png" --out "$TMP/seg_dup.json" \
    >/dev/null 2>&1
python3 "$SCRIPTS/spectral_segment_dup.py" \
    --image "$FIX/spectra/segment_clean.png" --out "$TMP/seg_clean.json" \
    >/dev/null 2>&1
if python3 - "$TMP" <<'PYTEST'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
dup = json.load(open(p / "seg_dup.json"))
clean = json.load(open(p / "seg_clean.json"))
assert dup["applicable"] is True
assert dup["significant_count"] >= 1, dup
assert dup["matches"][0]["score"] >= 0.985, dup["matches"][0]
assert clean["significant_count"] == 0, clean["matches"]
PYTEST
then ok "copied segment fires, clean trace stays silent"
else bad "segment duplication detector thresholds wrong"; fi

echo
echo "== 21. panel_split multi-cue fallback =="
mkdir -p "$TMP/panels2"
python3 "$SCRIPTS/panel_split.py" "$FIX/panels/figure_2panel.png" \
    "$TMP/panels2" --json "$TMP/panels2.json" >/dev/null 2>&1
if python3 - "$TMP/panels2.json" <<'PYTEST'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["panel_count"] >= 2, d
assert d["image_size"] == [700, 300], d["image_size"]
PYTEST
then ok "2-panel fixture splits with JSON evidence"
else bad "panel_split JSON/fallback failed"; fi

echo
echo "== 22. threshold calibration harness =="
python3 "$SCRIPTS/calibrate_image_thresholds.py"     --manifest "$FIX/calibration/manifest.json"     --output "$TMP/calibration.json" >/dev/null 2>&1
if python3 - "$TMP/calibration.json" <<'PYTEST'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["n_pairs"] == 5, d["n_pairs"]
assert "dhash_score" in d["metrics"], d["metrics"]
assert d["metrics"]["dhash_score"]["auc"] is not None
assert "curve_score" in d["metrics"], d["metrics"]
PYTEST
then ok "ROC/AUC calibration report is written"
else bad "calibration harness failed"; fi

echo
echo "== 23. ORB RANSAC geometry =="
python3 "$SCRIPTS/image_dup_orb.py" \
    "$FIX/images/dup_a.png" "$FIX/images/dup_b.png" "$FIX/images/diff.png" \
    --json "$TMP/orb.json" >"$TMP/orb.log" 2>&1 || true
if python3 - "$TMP/orb.json" <<'PYTEST'
import json, sys
d = json.load(open(sys.argv[1]))
pairs = {(p["a"], p["b"]): p for p in d["pairs"]}
key = ("dup_a.png", "dup_b.png")
assert key in pairs, pairs.keys()
assert pairs[key]["matches"] >= 30, pairs[key]
assert pairs[key]["inliers"] >= 10, pairs[key]
assert pairs[key]["inlier_ratio"] >= 0.5, pairs[key]
assert pairs[key]["bbox"] is not None, pairs[key]
assert ("dup_a.png", "diff.png") not in pairs, pairs.keys()
PYTEST
then ok "duplicate pair gets RANSAC inliers + bbox; unrelated pair is silent"
else bad "ORB geometry report invalid"; fi

echo
echo "== 24. NMR / HRMS isotope checks =="
python3 "$SCRIPTS/nmr_hrms_numeric.py" "$FIX/nmr" --output "$TMP/nmr_ok.json" >/dev/null 2>&1
python3 "$SCRIPTS/nmr_hrms_numeric.py" "$FIX/nmr_invalid" --output "$TMP/nmr_bad.json" >/dev/null 2>&1
if python3 - "$TMP" <<'PYTEST'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
ok = json.load(open(p / "nmr_ok.json"))
bad = json.load(open(p / "nmr_bad.json"))
assert ok["findings_count"] == 0, ok["findings"]
checks = {f["check"] for f in bad["findings"]}
assert "nmr_integration_noninteger" in checks, checks
assert "nmr_13c_count_exceeds_formula" in checks, checks
assert "nmr_13c_impossible_shift" in checks, checks
assert "hrms_rdbe_negative" in checks, checks
assert "hrms_isotope_intensity" in checks, checks
PYTEST
then ok "valid NMR silent; invalid integrations/13C/HRMS fire"
else bad "NMR/HRMS checker thresholds wrong"; fi

echo
echo "== 25. cross-paper corpus matcher =="
mkdir -p "$TMP/corpus"
python3 "$SCRIPTS/corpus_add.py" --corpus "$TMP/corpus" --key ref.1 \
    --doi 10.0000/test --title "fixture reference" \
    --figure "$FIX/images/dup_a.png" >"$TMP/corpus_add.log" 2>&1
python3 "$SCRIPTS/corpus_match.py" --query "$FIX/images/dup_b.png" \
    --corpus "$TMP/corpus" --json "$TMP/corpus_hit.json" >/dev/null 2>&1
python3 "$SCRIPTS/corpus_match.py" --query "$FIX/images/diff.png" \
    --corpus "$TMP/corpus" --json "$TMP/corpus_miss.json" >/dev/null 2>&1
if python3 - "$TMP" <<'PYTEST'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
hit = json.load(open(p / "corpus_hit.json"))
miss = json.load(open(p / "corpus_miss.json"))
assert hit["strong_count"] >= 1, hit
assert hit["candidates"][0]["inliers"] >= 10, hit["candidates"][0]
assert miss["candidates"] == [], miss
PYTEST
then ok "corpus hit has ORB inliers; unrelated query is silent"
else bad "cross-paper corpus matcher failed"; fi

echo
echo "== 26. offset-stacked trace splitting =="
rm -rf "$TMP/offset"
python3 "$SCRIPTS/offset_stack_split.py" "$FIX/panels/offset_2trace.png" \
    "$TMP/offset" --traces 2 --json "$TMP/offset.json" >/dev/null 2>&1
if python3 - "$TMP/offset.json" <<'PYTEST'
import json, sys, pathlib
d = json.load(open(sys.argv[1]))
assert len(d["cuts"]) == 1, d
assert len(d["bands"]) == 2, d
assert all(pathlib.Path(p).is_file() for p in d["bands"]), d["bands"]
PYTEST
then ok "two offset traces split without separator rules"
else bad "offset-stack splitter failed"; fi

echo
echo "== 27. executable report quality gate =="
python3 "$SCRIPTS/report_gate.py" "$FIX/report/valid.md" \
    --run-dir "$FIX/report" --json "$TMP/gate_ok.json" >/dev/null 2>&1
python3 "$SCRIPTS/report_gate.py" "$FIX/report/invalid.md" \
    --run-dir "$FIX/report" --json "$TMP/gate_bad.json" >/dev/null 2>&1 || true
python3 - "$FIX/report/valid.md" "$TMP/gate_noimg.md" <<'PYTEST'
import sys, pathlib
src, dst = map(pathlib.Path, sys.argv[1:])
text = src.read_text(encoding="utf-8")
cut = text.split("- **证据图**：")[1].split("## 4. 各线小结")[0]
dst.write_text(text.replace(cut, "\n"), encoding="utf-8")
PYTEST
python3 "$SCRIPTS/report_gate.py" "$TMP/gate_noimg.md" \
    --run-dir "$FIX/report" --json "$TMP/gate_noimg.json" >/dev/null 2>&1 || true
if python3 - "$TMP" <<'PYTEST'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
ok = json.load(open(p / "gate_ok.json"))
bad = json.load(open(p / "gate_bad.json"))
noimg = json.load(open(p / "gate_noimg.json"))
assert ok["pass"] is True and ok["errors"] == [], ok
assert bad["pass"] is False, bad
assert noimg["pass"] is False, noimg
msgs = " ".join(e["message"] for e in bad["errors"])
for needle in ("missing field", "unresolved placeholder", "verdict word"):
    assert needle in msgs, msgs
assert "证据图" in " ".join(e["message"] for e in noimg["errors"]), noimg
PYTEST
then ok "valid report passes; missing locator/placeholder/verdict word/证据图 fail"
else bad "report quality gate thresholds wrong"; fi

echo
echo "== 28. report figures =="
mkdir -p "$TMP/report_fig"
if python3 "$SCRIPTS/report_figures.py" --id smoke \
     --image "$FIX/images/dup_a.png" --box 40,40,240,200 \
     --output-dir "$TMP/report_fig" --run-dir "$TMP" \
     --caption "smoke figure" >/dev/null 2>&1; then
  if python3 - "$TMP/report_fig" <<'PYTEST'
import json, sys, pathlib
from PIL import Image
p = pathlib.Path(sys.argv[1])
m = json.load(open(p / "smoke_manifest.json"))
assert m["id"] == "smoke" and m["source_kind"] == "figure", m
assert (p / "smoke_source.png").is_file(), m
assert (p / "smoke_crop.png").is_file(), m
assert Image.open(p / "smoke_crop.png").size[0] > 200
PYTEST
  then ok "annotated source and enlarged crop are written"
  else bad "report_figures outputs invalid"; fi
else
  bad "report_figures run"
fi

echo
echo "======================================"
echo "PASS $PASS   FAIL $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
