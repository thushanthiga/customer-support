import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  skipTrailingSlashRedirect: true,
  allowedDevOrigins: ["192.168.8.34", "192.168.8.69", "192.168.8.209"],
  async rewrites() {
    const apiTarget = (process.env.SUPPORT_ASSISTANT_API_URL || "http://127.0.0.1:8000/api").replace(/\/$/, "");
    return [
      { source: "/api/:path*/", destination: `${apiTarget}/:path*/` },
      { source: "/api/:path*", destination: `${apiTarget}/:path*/` },
    ];
  },
};

export default nextConfig;
