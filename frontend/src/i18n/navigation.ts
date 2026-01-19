/**
 * Locale-aware navigation APIs for next-intl.
 *
 * These are lightweight wrappers around Next.js navigation APIs
 * that automatically handle the user's locale.
 *
 * Use these instead of importing directly from 'next/link' or 'next/navigation'.
 */
import { createNavigation } from "next-intl/navigation";
import { routing } from "./routing";

export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
