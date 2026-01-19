/**
 * Server-side i18n configuration for next-intl.
 *
 * This file is used by next-intl to load locale messages on the server.
 * For routing and navigation, see @/i18n/index.ts
 */
import { getRequestConfig } from "next-intl/server";
import { locales, defaultLocale, type Locale } from "./i18n/config";

// Re-export for backwards compatibility
export { locales, defaultLocale, getLocaleLabel, type Locale } from "./i18n/config";

export default getRequestConfig(async ({ requestLocale }) => {
  // This typically corresponds to the `[locale]` segment
  let locale = await requestLocale;

  // Ensure that a valid locale is used
  if (!locale || !locales.includes(locale as Locale)) {
    locale = defaultLocale;
  }

  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
  };
});
