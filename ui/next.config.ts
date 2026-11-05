import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  skipTrailingSlashRedirect: true,
  allowedDevOrigins: ["192.168.8.34", "192.168.8.69", "192.168.8.209"],
};

export default nextConfig;
