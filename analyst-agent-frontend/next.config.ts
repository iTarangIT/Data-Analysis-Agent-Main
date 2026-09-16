import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next's round dev badge is black, which is off-palette, and it sat on the sidebar's account
  // menu. Compile and runtime errors are still shown with it off.
  devIndicators: false,
};

export default nextConfig;
