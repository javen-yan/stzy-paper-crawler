export interface SampledFontEntry {
  font: string
  seen_count: number
  status: 'installed' | 'downloaded' | 'substituted' | 'missing' | string
  mapped_to?: string
  updated_at?: string
}

export interface FontStatus {
  font_config: boolean
  font_engine?: string
  libreoffice: string
  office_converter?: string
  policy: 'strict' | 'substitute' | string
  auto_install: boolean
  directories: string[]
  install_dir: string
  open_fonts_available: string[]
  open_fonts_installed: string[]
  open_fonts_missing: string[]
  sampled_fonts?: SampledFontEntry[]
  data_dir: string
  checked?: string[]
  resolved?: {
    exact: string[]
    substituted: Record<string, string>
    heuristic?: string[]
    missing: string[]
    warnings?: string[]
    policy: string
    visual_review: boolean
  }
  installed_now?: string[]
  warnings?: string[]
}
