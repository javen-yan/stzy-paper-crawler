export interface FontStatus {
  font_config: boolean
  libreoffice: string
  policy: 'strict' | 'substitute' | string
  auto_install: boolean
  directories: string[]
  install_dir: string
  open_fonts_available: string[]
  open_fonts_installed: string[]
  open_fonts_missing: string[]
  data_dir: string
  checked?: string[]
  resolved?: {
    exact: string[]
    substituted: Record<string, string>
    missing: string[]
    policy: string
    visual_review: boolean
  }
  installed_now?: string[]
  warnings?: string[]
}
