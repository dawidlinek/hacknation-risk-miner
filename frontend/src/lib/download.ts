import { markMockResponse } from '@/api/mockSignal'

function filenameFrom(res: Response, fallback: string): string {
  const cd = res.headers.get('content-disposition') ?? ''
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd)
  if (star) return decodeURIComponent(star[1])
  const plain = /filename="?([^";]+)"?/i.exec(cd)
  return plain ? plain[1] : fallback
}

/** fetch → blob → <a download>. Returns the filename used. Throws on non-2xx. */
export async function downloadFile(url: string, fallbackName: string, init?: RequestInit): Promise<string> {
  const res = await fetch(url, { credentials: 'include', ...init })
  markMockResponse(res)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const blob = await res.blob()
  const name = filenameFrom(res, fallbackName)
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
  return name
}
