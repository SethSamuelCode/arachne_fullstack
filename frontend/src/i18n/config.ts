/**
 * i18n configuration constants.
 *
 * Shared between server and client components.
 */

// Supported locales
export const locales = ["en", "pl"] as const;
export type Locale = (typeof locales)[number];

export const defaultLocale: Locale = "en";

export function getLocaleLabel(locale: Locale): string {
  const labels: Record<Locale, string> = {
    en: "English",
    pl: "Polski",
  };
  return labels[locale];
}
