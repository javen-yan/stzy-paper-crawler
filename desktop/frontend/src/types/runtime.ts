export type RuntimeMode = 'gui' | 'server'

export interface RuntimeInfo {
  mode: RuntimeMode
  host: string
  port: number
  public_base_url?: string
  capabilities: Record<string, boolean>
  preview: {
    max_pages: number
    max_pixels: number
    timeout_seconds: number
  }
}
