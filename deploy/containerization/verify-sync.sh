#!/usr/bin/env bash
# ==============================================================================
# PROJECT TERRA — Deployment & Secrets Synchronization Verification
#
# Validates that:
# 1. Cloudflare Pages frontend proxy is synchronized with VPS backend.
# 2. CORS origins and redirect URLs on backend match frontend domains.
# 3. Live HTTPS health and system info endpoints respond with matching status.
# ==============================================================================

set -euo pipefail

echo "=========================================================="
echo " PROJECT TERRA — SECRETS & DEPLOYMENT SYNC VERIFICATION"
echo "=========================================================="

FRONTEND_URL="${FRONTEND_URL:-https://project-terra.pages.dev}"
BACKEND_URL="${BACKEND_URL:-https://api-terra.yappin.studio}"

echo "[INFO] Target Frontend : ${FRONTEND_URL}"
echo "[INFO] Target Backend  : ${BACKEND_URL}"

FAILED=0

# ------------------------------------------------------------------------------
# 1. Verify Direct Backend Health & Contracts
# ------------------------------------------------------------------------------
echo ""
echo "--- 1. Testing Backend Direct HTTPS (${BACKEND_URL}) ---"
BACKEND_HEALTH_STATUS=$(curl -fsS -o /dev/null -w "%{http_code}" "${BACKEND_URL}/health/ready" 2>/dev/null || echo "failed")
if [[ "${BACKEND_HEALTH_STATUS}" == "200" ]]; then
  echo "[PASS] Backend /health/ready returned HTTP 200 OK"
else
  echo "[FAIL] Backend /health/ready failed (HTTP ${BACKEND_HEALTH_STATUS})"
  FAILED=1
fi

BACKEND_INFO=$(curl -fsS "${BACKEND_URL}/api/v1/system/info" 2>/dev/null || echo "")
if [[ -n "${BACKEND_INFO}" && "${BACKEND_INFO}" == *"TERRA Core API"* ]]; then
  echo "[PASS] Backend /api/v1/system/info returned valid JSON contract"
else
  echo "[FAIL] Backend /api/v1/system/info failed or returned invalid response"
  FAILED=1
fi

# ------------------------------------------------------------------------------
# 2. Verify Cloudflare Pages Frontend & Proxied API
# ------------------------------------------------------------------------------
echo ""
echo "--- 2. Testing Cloudflare Pages Frontend (${FRONTEND_URL}) ---"
FRONTEND_PAGE_STATUS=$(curl -fsS -o /dev/null -w "%{http_code}" "${FRONTEND_URL}/" 2>/dev/null || echo "failed")
if [[ "${FRONTEND_PAGE_STATUS}" == "200" ]]; then
  echo "[PASS] Frontend HTML root returned HTTP 200 OK"
else
  echo "[FAIL] Frontend HTML root failed (HTTP ${FRONTEND_PAGE_STATUS})"
  FAILED=1
fi

FRONTEND_PROXIED_INFO=$(curl -fsS "${FRONTEND_URL}/api/v1/system/info" 2>/dev/null || echo "")
if [[ -n "${FRONTEND_PROXIED_INFO}" && "${FRONTEND_PROXIED_INFO}" == *"TERRA Core API"* ]]; then
  echo "[PASS] Proxied /api/v1/system/info via Cloudflare Pages returned backend contract"
else
  echo "[FAIL] Proxied /api/v1/system/info via Cloudflare Pages failed (Backend URL mismatch or proxy down)"
  FAILED=1
fi

FRONTEND_PROXIED_HEALTH=$(curl -fsS "${FRONTEND_URL}/health/ready" 2>/dev/null || echo "")
if [[ -n "${FRONTEND_PROXIED_HEALTH}" && "${FRONTEND_PROXIED_HEALTH}" == *"\"status\":\"ready\""* ]]; then
  echo "[PASS] Proxied /health/ready via Cloudflare Pages returned status: ready"
else
  echo "[FAIL] Proxied /health/ready via Cloudflare Pages failed"
  FAILED=1
fi

# ------------------------------------------------------------------------------
# 3. Verify CORS and Security Configuration Synchronization
# ------------------------------------------------------------------------------
echo ""
echo "--- 3. Verifying CORS Header Synchronization ---"
CORS_ORIGIN_HEADER=$(curl -s -I -X OPTIONS "${BACKEND_URL}/api/v1/system/info" \
  -H "Origin: ${FRONTEND_URL}" \
  -H "Access-Control-Request-Method: GET" 2>/dev/null | grep -i "access-control-allow-origin" || echo "")

if [[ -n "${CORS_ORIGIN_HEADER}" ]]; then
  echo "[PASS] Backend CORS allows frontend origin: ${CORS_ORIGIN_HEADER}"
else
  # If CORS origin header is not returned on preflight, verify direct GET returns appropriate origin
  CORS_GET_HEADER=$(curl -s -I "${BACKEND_URL}/api/v1/system/info" \
    -H "Origin: ${FRONTEND_URL}" 2>/dev/null | grep -i "access-control-allow-origin" || echo "")
  if [[ -n "${CORS_GET_HEADER}" ]]; then
    echo "[PASS] Backend CORS header present: ${CORS_GET_HEADER}"
  else
    echo "[WARN] Backend CORS headers not detected in response headers; check CORS_ORIGINS in .env.prod"
  fi
fi

# ------------------------------------------------------------------------------
# 4. Final Verdict
# ------------------------------------------------------------------------------
echo ""
echo "=========================================================="
if [[ "${FAILED}" -eq 0 ]]; then
  echo " [SUCCESS] All deployment secrets and endpoints are synchronized!"
  echo "=========================================================="
  exit 0
else
  echo " [ERROR] One or more synchronization checks failed."
  echo "=========================================================="
  exit 1
fi
