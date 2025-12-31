
import { registerOTel } from "@vercel/otel";

export function register() {
  registerOTel({
    serviceName: "arachne_fullstack-frontend",
  });
}
