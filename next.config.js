/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    GITHUB_RAW_BASE: process.env.GITHUB_RAW_BASE || 'https://raw.githubusercontent.com/rmkenv/climatewire/main/data',
  },
}

module.exports = nextConfig
