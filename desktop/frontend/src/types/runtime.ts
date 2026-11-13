export type RuntimeMode = 'gui' | 'server'

export interface RuntimeInfo {
  mode: RuntimeMode
  host: string
  port: number
  public_base_url?: string
  office_engine?: string
  libreoffice_url?: string
  output_dir?: string
  capabilities: Record<string, boolean>
  preview: {
    max_pages: number
    max_pixels: number
    timeout_seconds: number
  }
}
