import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The repository also contains ui/, which has its own lockfile. Without this
  // Turbopack walks up, finds two, and guesses which project it is building.
  // Pinning the root removes the guess.
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
