import { t } from "./i18n";

/** Summary failure codes, grouped by the sentence that explains them. */
const SUMMARY_FAILURE_KEYS = {
  context_exceeded: "context_exceeded",
  summary_invalid: "summary_invalid",
  llm_unavailable: "llm_unavailable",
  provider_auth: "provider_auth",
  provider_quota: "provider_quota",
  provider_rate_limited: "provider_rate_limited",
  provider_timeout: "provider_timeout",
  provider_unavailable: "provider_unavailable",
  provider_bad_request: "provider_bad_request",
  provider_model_unavailable: "provider_model_unavailable",
  provider_invalid_output: "provider_invalid_output",
  provider_context_exceeded: "too_long",
  audio_too_large: "too_long",
  provider_unsupported: "provider_unsupported",
  consent_missing: "consent_missing",
  origin_mismatch: "origin_mismatch",
  secret_unavailable: "secret_unavailable",
} as const;

/** The translated sentence for a summary failure code; an unknown or missing code gets the generic one. */
export function summaryFailureText(cause?: string | null): string {
  const key = cause && cause in SUMMARY_FAILURE_KEYS
    ? SUMMARY_FAILURE_KEYS[cause as keyof typeof SUMMARY_FAILURE_KEYS]
    : "unknown";
  return t(`summary:failureCause.${key}`);
}
