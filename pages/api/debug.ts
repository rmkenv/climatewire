


import type { NextApiRequest, NextApiResponse } from 'next'

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const base = process.env.GITHUB_RAW_BASE ?? 'NOT SET'
  const testUrl = `${base}/drought.geojson`

  let fetchResult: any = null
  let fetchError: any = null

  try {
    const r = await fetch(testUrl)
    const text = await r.text()
    fetchResult = {
      status: r.status,
      ok: r.ok,
      contentType: r.headers.get('content-type'),
      bodyPreview: text.slice(0, 300),
    }
  } catch (e: any) {
    fetchError = e?.message
  }

  res.status(200).json({
    GITHUB_RAW_BASE: base,
    testUrl,
    fetchResult,
    fetchError,
  })
}

