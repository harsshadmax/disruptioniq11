import type { NextConfig } from "next";

// The app is a client-rendered console behind a login (token in the browser), so Cache Components, which needs
// every dynamic route to be statically enumerable, is switched off. Dynamic routes like /disruptions/[id] stay simple.
const nextConfig: NextConfig = {
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
