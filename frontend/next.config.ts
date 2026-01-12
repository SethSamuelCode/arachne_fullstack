import type { NextConfig } from "next";
import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin('./src/i18n.ts');

// Additional hosts to allow in CSP connect-src (e.g., S3/MinIO endpoint)
// NEXT_PUBLIC_S3_HOST should include protocol, e.g., "http://example.com:9055"
const additionalConnectSrc = process.env.NEXT_PUBLIC_S3_HOST || '';

// Content Security Policy directives
const ContentSecurityPolicy = `
  default-src 'self';
  script-src 'self' 'unsafe-eval' 'unsafe-inline';
  style-src 'self' 'unsafe-inline';
  img-src 'self' blob: data: https: ${additionalConnectSrc};
  font-src 'self' data:;
  connect-src 'self' ws: wss: http://localhost:* https://localhost:* ${additionalConnectSrc};
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'self';
`.replace(/\n/g, " ").replace(/\s+/g, " ").trim();

const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: ContentSecurityPolicy,
  },
  {
    key: "X-Content-Type-Options",
    value: "nosniff",
  },
  {
    key: "X-Frame-Options",
    value: "DENY",
  },
  {
    key: "X-XSS-Protection",
    value: "1; mode=block",
  },
  {
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
];

const nextConfig: NextConfig = {
  output: "standalone",

  // Security headers
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },

  // Environment variables available on the server side only
  serverRuntimeConfig: {
    apiUrl: process.env.BACKEND_URL || "http://localhost:8000",
  },

  // Environment variables available on both server and client
  publicRuntimeConfig: {
    appName: "arachne_fullstack",
  },
};
export default withNextIntl(nextConfig);
