/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async redirects() {
    return [
      {
        source: '/',
        destination: '/dashboard.html',
        permanent: false,
      },
    ]
  },
  env: {
    GITHUB_RAW_BASE: process.env.GITHUB_RAW_BASE || 'https://raw.githubusercontent.com/rmkenv/climatewire/main/data',
  },
}
module.exports = nextConfig
