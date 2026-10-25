import type { NextConfig } from "next";

// Куда проксировать /api в dev и в контейнере без nginx. В проде /api
// маршрутизирует nginx напрямую в FastAPI (решение Q21), сюда запросы не доходят.
// Rewrites вычисляются при сборке: в Docker адрес передаётся build-аргументом.
const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8100";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
