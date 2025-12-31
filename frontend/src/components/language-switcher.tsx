
'use client';

import { useLocale } from 'next-intl';
import { useRouter, usePathname } from 'next/navigation';
import { locales, type Locale, getLocaleLabel } from '@/i18n';

/**
 * Language switcher dropdown component.
 * Allows users to switch between available locales.
 */
export function LanguageSwitcher() {
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();

  const handleChange = (newLocale: Locale) => {
    // Remove the current locale from pathname and add the new one
    const segments = pathname.split('/');
    segments[1] = newLocale;
    const newPath = segments.join('/');
    router.push(newPath);
  };

  return (
    <div className="relative">
      <select
        value={locale}
        onChange={(e) => handleChange(e.target.value as Locale)}
        className="appearance-none bg-transparent border border-gray-300 dark:border-gray-600 rounded-md px-3 py-1.5 pr-8 text-sm cursor-pointer hover:border-gray-400 dark:hover:border-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
        aria-label="Select language"
      >
        {locales.map((loc) => (
          <option key={loc} value={loc}>
            {getLocaleLabel(loc)}
          </option>
        ))}
      </select>
      <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-gray-500">
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </div>
  );
}

/**
 * Compact language switcher with flag icons.
 */
export function LanguageSwitcherCompact() {
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();

  const flags: Record<Locale, string> = {
    en: '🇬🇧',
    pl: '🇵🇱',
  };

  const handleChange = (newLocale: Locale) => {
    const segments = pathname.split('/');
    segments[1] = newLocale;
    const newPath = segments.join('/');
    router.push(newPath);
  };

  return (
    <div className="flex gap-1">
      {locales.map((loc) => (
        <button
          key={loc}
          onClick={() => handleChange(loc)}
          className={`px-2 py-1 rounded-md text-lg transition-opacity ${
            locale === loc
              ? 'opacity-100 bg-gray-100 dark:bg-gray-800'
              : 'opacity-50 hover:opacity-75'
          }`}
          aria-label={getLocaleLabel(loc)}
          aria-pressed={locale === loc}
        >
          {flags[loc]}
        </button>
      ))}
    </div>
  );
}
