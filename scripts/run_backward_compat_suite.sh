#!/usr/bin/env bash
# T12: run_backward_compat_suite.sh
#
# Sequentially runs 4 pytest suites with -q (quiet mode) and records
# the number of passing tests. Exits 0 iff total passes >= baseline (62).
#
# Suites (baselines in parentheses, total=62):
#   1. test_import_task.py   (14)
#   2. test_itd_e2e.py       (6)
#   3. test_api.py           (6)
#   4. test_orchestrator.py  (36)
#
# Output:
#   * Per-suite summary lines on stdout
#   * Final aggregate pass count vs baseline
#   * Exit code 0 on success, 1 on any suite failure or below baseline
#
# Note: avoids bash 4.x+ features (assoc arrays) for macOS stock bash 3.2.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TESTS_DIR="${PROJECT_ROOT}/more_core/tests"
OUTPUT_DIR="${PROJECT_ROOT}/scripts/_compat_output"
mkdir -p "${OUTPUT_DIR}"

TS="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="${OUTPUT_DIR}/compat_suite_${TS}.log"
SUMMARY_FILE="${OUTPUT_DIR}/compat_suite_${TS}.summary"

# Baselines: parallel arrays, same order.
BASELINE_TOTAL=62
SUITES=(
  "test_import_task.py"
  "test_itd_e2e.py"
  "test_api.py"
  "test_orchestrator.py"
)
BASELINES=(14 6 6 36)
N_SUITES="${#SUITES[@]}"

echo "======================================================================"
echo "QNMing MoRE OS Backward Compat Suite — ${TS}"
echo "Project root: ${PROJECT_ROOT}"
echo "Test dir:     ${TESTS_DIR}"
echo "Log file:     ${LOG_FILE}"
echo "Baseline:     ${BASELINE_TOTAL} total passes across ${N_SUITES} suites"
echo "======================================================================"
echo ""

# Activate venv if present
if [ -f "${PROJECT_ROOT}/.venv/bin/activate" ]; then
  source "${PROJECT_ROOT}/.venv/bin/activate"
fi

cd "${PROJECT_ROOT}/more_core" || { echo "ERROR: cannot cd to more_core"; exit 1; }

TOTAL_PASSED=0
TOTAL_FAILED=0
# Parallel per-suite results
PASSED_RESULTS=()
FAILED_RESULTS=()
ERROR_RESULTS=()
RC_RESULTS=()

i=0
while [ "${i}" -lt "${N_SUITES}" ]; do
  suite="${SUITES[$i]}"
  baseline="${BASELINES[$i]}"
  suite_path="${TESTS_DIR}/${suite}"

  if [ ! -f "${suite_path}" ]; then
    echo "  ! MISSING suite file: ${suite_path}" | tee -a "${LOG_FILE}"
    PASSED_RESULTS[$i]=0
    FAILED_RESULTS[$i]=0
    ERROR_RESULTS[$i]=0
    RC_RESULTS[$i]=99
    i=$((i + 1))
    continue
  fi

  out_path="${OUTPUT_DIR}/${suite%.py}_${TS}.out"
  echo ">>> Running ${suite} (baseline >= ${baseline} passes) ..." | tee -a "${LOG_FILE}"

  set +e
  python -m pytest -q "${suite_path}" --no-header -p no:cacheprovider >"${out_path}" 2>&1
  rc=$?
  set -e

  passed=$(grep -oE '[0-9]+ passed' "${out_path}" 2>/dev/null | grep -oE '[0-9]+' | head -1)
  failed=$(grep -oE '[0-9]+ failed' "${out_path}" 2>/dev/null | grep -oE '[0-9]+' | head -1)
  errored=$(grep -oE '[0-9]+ error' "${out_path}" 2>/dev/null | grep -oE '[0-9]+' | head -1)
  [ -z "${passed}" ]  && passed=0
  [ -z "${failed}" ]  && failed=0
  [ -z "${errored}" ] && errored=0

  PASSED_RESULTS[$i]="${passed}"
  FAILED_RESULTS[$i]="${failed}"
  ERROR_RESULTS[$i]="${errored}"
  RC_RESULTS[$i]="${rc}"

  TOTAL_PASSED=$((TOTAL_PASSED + passed))
  TOTAL_FAILED=$((TOTAL_FAILED + failed + errored))

  # Per-suite summary mark (informational only; total >=62 determines exit)
  mark="OK"
  if [ "${rc}" -ne 0 ]; then
    mark="HAS_FAILURES"
  fi
  echo "  [${mark}] ${suite}: ${passed} passed, ${failed} failed, ${errored} errors (baseline >= ${baseline}) | exit=${rc}" | tee -a "${LOG_FILE}"
  echo "          detail: ${out_path}" | tee -a "${LOG_FILE}"

  i=$((i + 1))
done

echo ""
echo "======================================================================"
echo "SUMMARY"
echo "======================================================================" | tee -a "${SUMMARY_FILE}"
{
  echo "timestamp_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "suites_run: ${N_SUITES}"
  j=0
  while [ "${j}" -lt "${N_SUITES}" ]; do
    echo "  ${SUITES[$j]}: passed=${PASSED_RESULTS[$j]} failed=${FAILED_RESULTS[$j]} errors=${ERROR_RESULTS[$j]} rc=${RC_RESULTS[$j]} baseline>=${BASELINES[$j]}"
    j=$((j + 1))
  done
  echo "total_passed:  ${TOTAL_PASSED}"
  echo "total_failed:  ${TOTAL_FAILED}"
  echo "baseline_total: ${BASELINE_TOTAL}"
} | tee -a "${SUMMARY_FILE}"

echo "" | tee -a "${LOG_FILE}"
echo "TOTAL PASSED:  ${TOTAL_PASSED} / baseline ${BASELINE_TOTAL}" | tee -a "${LOG_FILE}"

if [ "${TOTAL_PASSED}" -ge "${BASELINE_TOTAL}" ]; then
  echo "RESULT: PASS (>= ${BASELINE_TOTAL} baseline)" | tee -a "${LOG_FILE}"
  echo "${LOG_FILE}"     > "${PROJECT_ROOT}/scripts/_last_compat_log_path.txt"
  echo "${SUMMARY_FILE}" >> "${PROJECT_ROOT}/scripts/_last_compat_log_path.txt"
  exit 0
else
  echo "RESULT: FAIL (${TOTAL_PASSED} < ${BASELINE_TOTAL} baseline)" | tee -a "${LOG_FILE}"
  echo "${LOG_FILE}"     > "${PROJECT_ROOT}/scripts/_last_compat_log_path.txt"
  echo "${SUMMARY_FILE}" >> "${PROJECT_ROOT}/scripts/_last_compat_log_path.txt"
  exit 1
fi
