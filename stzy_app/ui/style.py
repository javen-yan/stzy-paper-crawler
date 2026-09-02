LIGHT_THEME_CSS = """
:root {
  --stzy-accent: #2563eb;
  --stzy-accent-soft: #eff6ff;
  --stzy-border: #e5e7eb;
  --stzy-muted: #667085;
  --stzy-bg: #f8fafc;
  --stzy-danger: #b42318;
  --stzy-header-height: 56px;
  --stzy-footer-height: 44px;
  --stzy-z-footer: 20;
}
body {
  margin: 0;
  background: var(--stzy-bg);
  color: #1f2937;
}
html,
body,
#app {
  height: 100%;
  overflow: hidden;
}
.q-page,
.q-page-container {
  min-height: 0 !important;
  overflow: hidden;
}
.nicegui-content {
  padding: 0 !important;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.stzy-shell {
  display: grid;
  height: 100dvh;
  max-height: 100dvh;
  grid-template-rows: auto minmax(0, 1fr) auto;
  background: var(--stzy-bg);
  overflow: hidden;
}
.topbar {
  height: var(--stzy-header-height);
  border-bottom: 1px solid var(--stzy-border);
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
}
.topbar-inner {
  width: min(1500px, calc(100vw - 40px));
  height: 100%;
  margin: 0 auto;
  gap: 18px;
}
.topbar-left {
  flex: 1 1 auto;
  min-width: 0;
  gap: 24px;
}
.topbar-brand {
  flex: 0 0 auto;
  min-width: 118px;
}
.topbar-config {
  flex: 1 1 auto;
  min-width: 360px;
  overflow: hidden;
}
.config-summary-strip {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: 6px;
  overflow: hidden;
}
.config-summary-item {
  display: inline-flex;
  min-width: 0;
  max-width: 190px;
  height: 30px;
  align-items: center;
  gap: 4px;
  padding: 0 6px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #475569;
  cursor: pointer;
}
.config-summary-item:hover {
  background: #f1f5f9;
}
.config-summary-item i {
  flex: 0 0 auto;
  color: var(--stzy-accent);
  font-size: 16px;
}
.config-summary-title,
.config-summary-item strong,
.config-summary-item small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1;
}
.config-summary-title {
  color: #64748b;
  font-size: 12px;
}
.config-summary-item strong {
  color: #1f2937;
  font-size: 12px;
  font-weight: 650;
}
.config-summary-item small {
  max-width: 68px;
  color: #94a3b8;
  font-size: 11px;
}
.topbar-config .config-summary-item small {
  display: none;
}
.config-summary-warn strong,
.config-summary-warn i {
  color: #b54708;
}
.topbar-actions {
  flex: 0 0 auto;
  min-width: 0;
}
.topbar-network {
  min-width: 168px;
  max-width: 230px;
  height: 36px;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid #dbeafe;
  border-radius: 8px;
  background: #f8fbff;
  box-sizing: border-box;
}
.topbar-network-icon {
  color: #3b82f6;
  font-size: 18px;
}
.topbar-network-label {
  color: var(--stzy-muted);
  font-size: 12px;
  white-space: nowrap;
}
.topbar-network-value {
  min-width: 0;
  overflow: hidden;
  color: #1f2937;
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.config-drawer {
  width: min(440px, 100vw) !important;
  min-width: min(440px, 100vw) !important;
  background: #ffffff;
  border-left: 0 !important;
}
.q-drawer.config-drawer {
  min-width: min(440px, 100vw) !important;
  border-left: 0 !important;
}
.config-drawer-body {
  height: 100dvh;
  min-height: 0;
  gap: 12px;
  padding: 0;
  box-sizing: border-box;
  overflow: hidden;
}
.config-drawer-head {
  flex: 0 0 auto;
  min-height: 38px;
  padding: 16px 18px 0;
}
.config-tabs {
  flex: 0 0 auto;
  width: calc(100% - 36px);
  margin: 0 18px;
  padding: 2px;
  border: 0;
  border-radius: 8px;
  background: #f8fafc;
}
.config-tabs .q-tabs__content {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  width: 100%;
}
.config-tabs .q-tab {
  min-height: 34px;
  min-width: 0;
  padding: 0 5px;
  border-radius: 6px;
}
.config-tabs .q-tab__icon {
  font-size: 16px;
  margin-bottom: 0;
}
.config-tabs .q-tab__content {
  min-width: 0;
  flex-direction: row;
  gap: 4px;
  flex-wrap: nowrap;
}
.config-tabs .q-tab__label {
  font-size: 12px;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.config-tabs .q-tab--active {
  background: #ffffff;
  color: var(--stzy-accent);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}
.config-tabs .q-tab__indicator {
  display: none;
}
.config-panels {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  background: transparent;
  overflow: hidden;
}
.config-panels .q-panel {
  min-height: 0;
  overflow: hidden;
}
.config-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 2px 18px 0;
  overflow-y: auto;
  overflow-x: hidden;
}
.config-panel-title {
  color: #111827;
  font-size: 15px;
  font-weight: 650;
}
.config-panel-note {
  min-height: 24px;
  color: var(--stzy-muted);
  font-size: 13px;
}
.path-config-row {
  gap: 10px;
}
.path-config-input {
  flex: 1 1 auto;
  min-width: 0;
}
.path-config-button,
.drawer-primary {
  min-height: 44px;
}
.drawer-primary {
  align-self: flex-end;
  min-width: 128px;
}
.drawer-actions {
  position: sticky;
  bottom: -1px;
  z-index: 2;
  gap: 10px;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
  background: #ffffff;
}
.drawer-settings-grid {
  grid-template-columns: 1fr;
}
.drawer-proxy-fields {
  grid-template-columns: 1fr;
}
.config-drawer .account-list {
  max-height: 188px;
  gap: 8px;
}
.config-drawer .account-item {
  grid-template-columns: 34px minmax(0, 1fr) 76px;
  gap: 8px 10px;
  align-items: start;
  padding: 10px 12px;
}
.config-drawer .account-order-pill {
  width: 28px;
  height: 28px;
  border-radius: 14px;
  font-size: 12px;
  margin-top: 2px;
}
.config-drawer .account-identity {
  grid-column: 2 / 3;
  min-width: 0;
}
.config-drawer .account-meta-line {
  gap: 4px 8px;
}
.config-drawer .account-status {
  grid-column: 2 / 3;
  grid-row: 2;
  justify-self: start;
  min-width: 58px;
  height: 24px;
  font-size: 12px;
}
.config-drawer .account-auth {
  grid-column: 2 / 3;
  grid-row: 3;
  justify-self: start;
  color: #64748b;
  font-size: 12px;
  line-height: 1.4;
}
.config-drawer .account-row-actions {
  grid-column: 3 / 4;
  grid-row: 1 / span 3;
  align-self: center;
  justify-self: end;
  flex-wrap: nowrap;
}
.drawer-account-tabs {
  border-bottom: 0;
  padding: 2px;
  border-radius: 8px;
  background: #f8fafc;
}
.drawer-account-tabs .q-tabs__content {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  width: 100%;
}
.drawer-account-tabs .q-tab {
  min-height: 34px;
  padding: 0 8px;
  border-radius: 6px;
}
.drawer-account-tabs .q-tab__content {
  flex-direction: row;
  gap: 4px;
}
.drawer-account-tabs .q-tab__indicator {
  display: none;
}
.drawer-account-tabs .q-tab--active {
  background: #ffffff;
  color: var(--stzy-accent);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}
.drawer-account-form {
  gap: 12px;
  padding: 12px;
  background: #ffffff;
}
.config-drawer .account-actions {
  bottom: -12px;
  margin: 0 -12px -12px;
  padding: 10px 12px 12px;
  background: #ffffff;
}
.result-expansion {
  border: 1px solid var(--stzy-border);
  border-radius: 8px;
  overflow: hidden;
}
.result-expansion .q-item {
  min-height: 44px;
  background: #f9fafb;
  color: #111827;
  font-weight: 650;
}
.result-expansion .q-expansion-item__content {
  padding: 12px;
  background: #ffffff;
}
.panel {
  background: #fff;
  border: 1px solid var(--stzy-border);
  border-radius: 8px;
}
.main-wrap {
  width: min(1500px, calc(100vw - 40px));
  margin: 0 auto;
  height: 100%;
  max-height: calc(100dvh - var(--stzy-header-height) - var(--stzy-footer-height));
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  box-sizing: border-box;
}
.workbench {
  display: grid;
  width: 100%;
  grid-template-columns: minmax(0, 1.7fr) minmax(360px, 0.85fr);
  gap: 20px;
  align-items: start;
}
.left-stack {
  width: 100%;
  min-width: 0;
}
.main-wrap > .panel,
.workbench > .panel {
  width: 100%;
  box-sizing: border-box;
}
.workbench > .left-stack > .panel {
  width: 100%;
  box-sizing: border-box;
}
.hero-panel {
  background: linear-gradient(180deg, #ffffff 0%, #f9fbff 100%);
}
.section-title {
  font-size: 16px;
  line-height: 1.4;
  font-weight: 650;
  color: #111827;
}
.quick-filter {
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #f8fbff;
  box-sizing: border-box;
}
.quick-filter-head {
  min-height: 22px;
}
.quick-filter-title {
  color: #1d4ed8;
  font-size: 13px;
  font-weight: 650;
}
.quick-filter-fields {
  display: grid;
  width: 100%;
  grid-template-columns: minmax(0, 0.75fr) repeat(5, minmax(0, 1fr)) minmax(132px, 150px);
  gap: 12px;
  align-items: end;
}
.quick-filter-input,
.quick-filter-input .q-field {
  width: 100%;
  min-width: 0;
}
.quick-filter-button {
  height: 44px;
  min-width: 0;
}
.quick-filter-button .q-btn__content {
  min-width: 0;
}
.step-action .q-btn__content {
  gap: 8px;
  white-space: nowrap;
}
.step-action .q-btn__content span.block {
  font-weight: 650;
}
.step-action-one {
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.16);
}
.step-action-two {
  border-color: #93c5fd;
  color: #1d4ed8;
  background: #ffffff;
}
.step-action-three {
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
}
.advanced-filter {
  border: 1px solid var(--stzy-border);
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
  margin: 10px 0 14px;
}
.advanced-filter .q-item {
  min-height: 54px;
  padding: 0 12px;
  background: #f9fafb;
  color: #111827;
  font-weight: 600;
}
.advanced-filter .q-item__section,
.advanced-filter .q-item__label {
  min-width: 0;
  line-height: 1.4;
}
.advanced-filter .q-item__section--main {
  padding: 10px;
}
.advanced-filter .q-expansion-item__content {
  padding: 16px;
  border-top: 1px solid #eef2f7;
  background: #fff;
}
.download-section {
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: 10px;
  box-sizing: border-box;
  padding-top: 4px;
}
.task-control-panel {
  padding: 14px 16px 16px;
  border: 1px solid #dbeafe;
  border-radius: 8px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
}
.task-control-head {
  min-height: 24px;
}
.task-control-title,
.subsection-title {
  color: #111827;
  font-size: 14px;
  font-weight: 650;
}
.task-context {
  max-width: 52%;
  color: var(--stzy-muted);
  font-size: 12px;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-action-hint {
  color: var(--stzy-muted);
  font-size: 12px;
  line-height: 1.5;
}
.filter-list {
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: 8px;
}
.filter-row {
  display: grid;
  width: 100%;
  grid-template-columns: 54px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--stzy-border);
}
.filter-row-label {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  color: var(--stzy-muted);
  font-size: 13px;
}
.filter-toggle {
  display: block;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}
.filter-toggle .q-btn-group {
  display: flex;
  flex-wrap: wrap !important;
  gap: 6px 10px;
  box-shadow: none;
  border-radius: 0;
  background: transparent;
  align-items: flex-start;
  width: 100%;
  min-width: 0;
  max-width: 100%;
}
.filter-toggle .q-btn-group.no-wrap,
.filter-toggle .q-btn-toggle.no-wrap {
  flex-wrap: wrap !important;
}
.filter-toggle .q-btn {
  flex: 0 0 auto !important;
  width: auto !important;
  min-height: 30px;
  min-width: 0;
  max-width: 100%;
  padding: 4px 8px;
  border: 1px solid transparent;
  border-radius: 4px !important;
  color: #111827;
  font-size: 13px;
  line-height: 1.3;
  white-space: nowrap;
}
.filter-toggle .q-btn__content {
  flex-wrap: nowrap;
  white-space: nowrap;
  word-break: keep-all;
  line-height: 1.3;
}
.filter-toggle .q-btn[aria-pressed="true"],
.filter-toggle .q-btn.bg-primary,
.filter-toggle .q-btn.text-primary {
  border-color: var(--stzy-accent);
  background: var(--stzy-accent-soft) !important;
  color: var(--stzy-accent) !important;
}
.filter-more .q-item {
  min-height: 34px;
  padding: 4px 0;
}
.filter-more .q-expansion-item__content {
  padding-top: 8px;
}
.settings-grid > *,
.settings-grid .q-field {
  width: 100%;
  min-width: 0;
}
.settings-grid {
  display: grid;
  width: 100%;
  grid-template-columns: minmax(0, 1fr) 180px;
  gap: 18px;
  align-items: end;
}
.proxy-mode-toggle {
  width: 100%;
}
.proxy-mode-toggle .q-btn-group {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 3px;
  width: 100%;
  padding: 3px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f8fafc;
  box-shadow: none;
}
.proxy-mode-toggle .q-btn {
  min-height: 34px;
  min-width: 0;
  padding: 4px 8px;
  border-radius: 6px !important;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}
.proxy-mode-toggle .q-btn.bg-primary,
.proxy-mode-toggle .q-btn.text-primary,
.proxy-mode-toggle .q-btn[aria-pressed="true"] {
  background: #ffffff !important;
  color: var(--stzy-accent) !important;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}
.proxy-fields {
  display: grid;
  grid-template-columns: minmax(180px, 0.72fr) minmax(0, 1.28fr);
  gap: 12px 14px;
  align-items: end;
  min-width: 0;
}
.proxy-api-wrap,
.proxy-pool-wrap,
.proxy-whitelist-wrap {
  grid-column: 1 / -1;
}
.proxy-whitelist-wrap {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 14px;
  min-width: 0;
}
.compact-field .q-field__control,
.compact-field .q-field__native,
.compact-field .q-field__marginal {
  min-height: 44px;
}
.compact-field .q-field__label {
  font-size: 12px;
}
.proxy-pool-input textarea {
  min-height: 76px !important;
  max-height: 128px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
  word-break: break-all;
  white-space: pre-wrap;
}
.metric-grid {
  display: grid;
  width: 100%;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.muted {
  color: var(--stzy-muted);
}
.log-box {
  display: block;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  height: 170px;
  overflow: auto;
  border-radius: 6px;
  border: 1px solid var(--stzy-border);
  background: #fbfcfd;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  padding: 10px;
}
.log-line {
  color: #344054;
}
.log-line-error {
  color: #b42318;
  font-weight: 650;
}
.log-line-warning {
  color: #b54708;
  font-weight: 650;
}
.log-line-filter {
  color: #1d4ed8;
}
.log-line-success {
  color: #027a48;
}
.runtime-log {
  border-top: 1px solid var(--stzy-border);
  padding-top: 12px;
}
.runtime-log-drawer {
  position: relative;
  z-index: var(--stzy-z-footer);
  width: 100%;
  max-height: min(310px, calc(100vh - 96px));
  overflow: hidden;
  border-top: 1px solid #d0d5dd;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 -4px 16px rgba(15, 23, 42, 0.06);
}
.runtime-log-drawer:not([open]) {
  height: 44px;
}
.runtime-log-summary {
  display: flex;
  width: min(1500px, calc(100vw - 40px));
  height: 44px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 0 auto;
  padding: 0;
  cursor: pointer;
  list-style: none;
  border-bottom: 1px solid transparent;
  background: transparent;
  color: #344054;
}
.runtime-log-summary::-webkit-details-marker {
  display: none;
}
.runtime-log-drawer[open] .runtime-log-summary {
  border-bottom-color: #e5e7eb;
}
.runtime-log-title {
  color: #475467;
  font-size: 12px;
  font-weight: 600;
}
.log-counter-wrap {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}
.log-counter {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #475467;
  font-size: 14px;
  font-weight: 700;
}
.log-counter-icon {
  color: #667085;
  font-size: 20px;
}
.log-counter-error.has-issues,
.log-counter-error.has-issues .log-counter-icon {
  color: #b42318;
}
.log-counter-error.has-issues {
  color: #b42318;
}
.log-counter-warning.has-issues,
.log-counter-warning.has-issues .log-counter-icon {
  color: #b54708;
}
.log-counter-filter.has-issues,
.log-counter-filter.has-issues .log-counter-icon {
  color: #1d4ed8;
}
.runtime-log-panel {
  width: min(1500px, calc(100vw - 40px));
  max-height: 250px;
  margin: 0 auto;
  padding: 10px;
  overflow: hidden;
  background: #fff;
}
.runtime-log-head {
  min-height: 32px;
}
.progress-panel .q-expansion-item,
.progress-panel .q-expansion-item__container,
.progress-panel .q-expansion-item__content,
.progress-panel .q-card,
.progress-panel .q-card__section {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.history-panel {
  width: 100%;
  box-sizing: border-box;
}
.task-history-table {
  overflow: hidden;
}
.task-history-table td,
.task-history-table th {
  white-space: nowrap;
}
.task-history-table td:nth-child(2) {
  max-width: 520px;
  white-space: normal;
}
.history-pagination {
  min-height: 34px;
  padding-top: 2px;
}
.history-pagination .q-btn {
  min-width: 72px;
}
.task-history-table .q-td:last-child {
  white-space: nowrap;
}
.table-empty-state {
  display: flex;
  width: 100%;
  min-height: 52px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #667085;
  font-size: 13px;
}
.table-empty-state .q-icon {
  color: #98a2b3;
}
.task-row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}
.task-action-btn {
  min-height: 28px;
  padding: 0 8px;
}
.task-action-manage {
  background: #eff6ff;
  color: #1d4ed8;
}
.task-action-open {
  color: #344054;
}
.task-action-cancel {
  color: #b42318;
}
.task-action-archive {
  color: #667085;
}
.history-status-badge {
  display: inline-flex;
  min-width: 64px;
  align-items: center;
  justify-content: center;
  padding: 3px 9px;
  border: 1px solid var(--stzy-border);
  border-radius: 999px;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.4;
}
.history-status-done {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #027a48;
}
.history-status-partial,
.history-status-paused {
  border-color: #fedf89;
  background: #fffaeb;
  color: #b54708;
}
.history-status-failed {
  border-color: #fecaca;
  background: #fef2f2;
  color: var(--stzy-danger);
}
.history-status-running {
  border-color: #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
}
.history-status-idle {
  color: #475467;
}
.compact-table .q-table__top,
.compact-table .q-table__bottom {
  min-height: 36px;
}
.compact-table td,
.compact-table th {
  font-size: 12px;
}
.compact-table td {
  vertical-align: top;
}
.current-result-table .q-table__middle {
  overflow-x: hidden;
}
.current-result-table .q-table {
  width: 100%;
  table-layout: fixed;
}
.current-result-table th:nth-child(2),
.current-result-table td:nth-child(2) {
  width: 64px;
}
.current-result-table th:nth-child(3),
.current-result-table td:nth-child(3) {
  width: 92px;
}
.current-result-table th:nth-child(4),
.current-result-table td:nth-child(4) {
  width: 112px;
}
.record-name-td {
  min-width: 0;
}
.record-name-cell {
  width: 100%;
  min-width: 0;
  color: #111827;
  line-height: 1.45;
  overflow-wrap: anywhere;
  white-space: normal;
}
.record-status {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: #f3f4f6;
  color: #374151;
}
.record-status-completed {
  background: #ecfdf3;
  color: #027a48;
}
.record-status-partial {
  background: #fffaeb;
  color: #b54708;
}
.record-status-skipped_paid {
  background: #f8fafc;
  color: #667085;
}
.record-status-paid_unavailable {
  background: #fff7ed;
  color: #c2410c;
}
.record-status-failed {
  background: #fef3f2;
  color: var(--stzy-danger);
}
.record-status-downloading {
  background: #eff6ff;
  color: #1d4ed8;
}
.record-error {
  margin-top: 4px;
  max-width: 220px;
  color: var(--stzy-muted);
  font-size: 11px;
  line-height: 1.35;
  white-space: normal;
}
.task-progress-wrap {
  position: relative;
  margin-top: -8px;
}
.task-progress {
  height: 12px;
  border-radius: 999px;
  overflow: hidden;
}
.task-progress-label {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 11px;
  font-weight: 650;
  line-height: 1;
  pointer-events: none;
}
.status-overview {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 54px;
  border: 1px solid var(--stzy-border);
  border-radius: 8px;
  background: #f8fafc;
  color: #111827;
  padding: 10px 14px;
  box-sizing: border-box;
}
.status-stage {
  font-size: 16px;
  line-height: 1.25;
  font-weight: 700;
}
.status-detail {
  margin-top: 3px;
  color: var(--stzy-muted);
  font-size: 12px;
  line-height: 1.35;
}
.status-overview strong {
  color: currentColor;
  font-size: 24px;
  line-height: 1;
}
.status-running {
  border-color: #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
}
.status-done {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #027a48;
}
.status-estimated {
  border-color: #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
}
.status-partial {
  border-color: #fedf89;
  background: #fffaeb;
  color: #b54708;
}
.status-limited {
  border-color: #fedf89;
  background: #fffaeb;
  color: #b54708;
}
.status-failed {
  border-color: #fecaca;
  background: #fef2f2;
  color: var(--stzy-danger);
}
.status-paused {
  border-color: #cbd5e1;
  background: #f8fafc;
  color: #475467;
}
.status-idle {
  border-color: var(--stzy-border);
  background: #f8fafc;
  color: #475467;
}
.status-overview .status-stage,
.status-overview .status-detail {
  max-width: 260px;
}
.action-grid {
  display: grid;
  width: 100%;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  align-items: center;
  padding-top: 0;
}
.action-grid .q-btn,
.path-config-row .q-btn {
  width: 100%;
}
.primary-action {
  height: 40px;
}
.secondary-action {
  height: 40px;
}
.task-control-action {
  min-width: 0;
}
.action-grid .q-btn[disabled] {
  opacity: 0.48;
}
.status-task-control {
  padding: 0 0 4px;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.status-task-control .task-context {
  max-width: 44%;
}
.status-action-flow {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.stop-action {
  grid-column: 1 / -1;
  color: #475467;
  border-color: #cbd5e1;
  background: #ffffff;
}
.stop-action:not([disabled]) {
  color: var(--stzy-danger);
  border-color: #fca5a5;
  background: #fef2f2;
}
.managed-task-label {
  min-height: 18px;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.5;
}
.current-result-head {
  min-height: 24px;
  padding-top: 2px;
  border-top: 1px solid #eef2f7;
}
.modal-card {
  width: min(720px, calc(100vw - 32px));
  border-radius: 8px;
  padding: 20px;
}
.account-list {
  display: flex;
  width: 100%;
  max-height: 220px;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
}
.account-item {
  display: grid;
  width: 100%;
  grid-template-columns: 56px minmax(280px, 1fr) 96px 104px 88px;
  gap: 14px;
  align-items: center;
  padding: 12px 14px;
  border: 1px solid var(--stzy-border);
  border-radius: 8px;
  background: #fff;
  box-sizing: border-box;
}
.account-order-pill {
  display: inline-flex;
  width: 36px;
  height: 36px;
  align-items: center;
  justify-content: center;
  border-radius: 18px;
  background: #f1f5f9;
  color: #475569;
  font-weight: 650;
}
.account-identity {
  min-width: 0;
}
.account-name-main {
  color: #111827;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.account-meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  margin-top: 4px;
  color: var(--stzy-muted);
  font-size: 12px;
  line-height: 1.4;
}
.account-meta-chip {
  max-width: 170px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.account-status {
  display: inline-flex;
  min-width: 64px;
  height: 28px;
  align-items: center;
  justify-content: center;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
}
.account-status.is-ok {
  border-color: #86efac;
  color: #15803d;
  background: #f0fdf4;
}
.account-status.is-warn {
  border-color: #fbbf24;
  color: #b45309;
  background: #fffbeb;
}
.account-status.is-danger {
  border-color: #fca5a5;
  color: var(--stzy-danger);
  background: #fef2f2;
}
.account-status.is-muted {
  color: #64748b;
  background: #f8fafc;
}
.account-auth {
  color: #334155;
  font-size: 14px;
  font-weight: 600;
}
.account-row-actions {
  gap: 4px;
  justify-content: flex-end;
}
.account-row-actions .q-btn {
  min-width: 36px;
}
.account-empty {
  display: flex;
  min-height: 118px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  background: #fff;
}
.account-empty-icon {
  color: #94a3b8;
  font-size: 28px;
}
.account-empty-title {
  color: #111827;
  font-weight: 650;
}
.account-tabs {
  width: 100%;
  border-bottom: 1px solid var(--stzy-border);
}
.account-tabs .q-tab {
  min-height: 42px;
  padding: 0 18px;
}
.account-panels {
  width: 100%;
  background: transparent;
  flex: 1 1 auto;
  min-height: 0;
}
.account-panels .q-panel {
  overflow: visible;
}
.account-panel {
  padding: 0;
}
.account-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: 100%;
  box-sizing: border-box;
  padding: 16px;
  border: 1px solid var(--stzy-border);
  border-radius: 8px;
  background: #fbfcff;
}
.account-enabled {
  margin-right: -8px;
}
.credential-grid {
  display: grid;
  width: 100%;
  grid-template-columns: 1fr;
  gap: 12px;
}
.credential-input textarea {
  min-height: 86px;
  max-height: 180px;
}
.console-script-box {
  width: 100%;
  padding: 12px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  background: #fff;
}
.console-script textarea {
  height: 150px !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  overflow: auto !important;
}
.auth-import-box textarea {
  min-height: 120px;
  max-height: 170px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre;
  word-break: normal;
  overflow-wrap: normal;
  overflow: auto !important;
}
.account-actions {
  position: sticky;
  bottom: -16px;
  z-index: 2;
  gap: 12px;
  margin: 0 -16px -16px;
  padding: 12px 16px 16px;
  border-top: 1px solid #e5e7eb;
  background: #fbfcff;
}
.account-actions .q-btn {
  min-width: 120px;
}
.dialog-primary {
  align-self: flex-end;
  min-width: 112px;
}
.metric {
  border: 1px solid var(--stzy-border);
  border-radius: 8px;
  padding: 8px 10px;
  background: #fff;
}
.metric-value {
  font-size: 18px;
  line-height: 1;
  font-weight: 700;
  color: #111827;
}
.metric-label {
  margin-top: 4px;
  color: var(--stzy-muted);
  font-size: 12px;
}
.empty-state {
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  background: #f8fafc;
  color: var(--stzy-muted);
  padding: 22px;
  text-align: center;
}
@media (max-width: 900px) {
  .main-wrap {
    width: calc(100vw - 20px);
  }
  .topbar {
    height: auto;
    min-height: 56px;
    padding: 0;
  }
  .topbar-inner {
    flex-wrap: wrap;
    gap: 8px;
    justify-content: flex-start;
    padding: 8px 0;
  }
  .topbar-left {
    width: 100%;
    flex-wrap: wrap;
    gap: 10px 16px;
  }
  .topbar-config {
    width: 100%;
    min-width: 0;
    order: 3;
  }
  .config-summary-strip {
    flex-wrap: wrap;
  }
  .config-summary-item {
    max-width: calc(50% - 4px);
    flex: 1 1 calc(50% - 4px);
  }
  .topbar-actions {
    width: 100%;
    flex-wrap: wrap;
  }
  .account-item {
    grid-template-columns: 44px minmax(0, 1fr) 88px;
    gap: 10px;
  }
  .account-status,
  .account-auth {
    justify-self: start;
  }
  .account-row-actions {
    grid-column: 3;
    grid-row: 1 / span 2;
  }
  .account-name-main {
    white-space: normal;
  }
  .workbench,
  .settings-grid,
  .drawer-settings-grid,
  .proxy-fields,
  .proxy-whitelist-wrap {
    grid-template-columns: 1fr;
  }
  .proxy-mode-toggle .q-btn-group {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    width: 100%;
  }
  .proxy-mode-toggle .q-btn {
    min-width: 0;
    padding: 6px 8px;
  }
  .filter-row {
    grid-template-columns: 42px minmax(0, 1fr);
  }
  .quick-filter-fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .quick-filter-fields .quick-filter-button {
    grid-column: 1 / -1;
  }
}
@media (max-width: 560px) {
  .metric-grid,
  .action-grid {
    grid-template-columns: 1fr;
  }
  .config-summary-item {
    max-width: 100%;
    flex-basis: 100%;
  }
  .config-drawer-body {
    padding: 0;
  }
  .config-drawer-head {
    padding: 14px 14px 0;
  }
  .config-tabs {
    width: calc(100% - 28px);
    margin: 0 14px;
  }
  .config-panel {
    padding: 2px 14px 0;
  }
  .config-tabs .q-tab {
    min-width: 0;
    padding: 0 6px;
  }
  .path-config-row,
  .drawer-actions {
    align-items: stretch;
    flex-direction: column;
  }
  .path-config-button,
  .drawer-actions .q-btn,
  .drawer-primary {
    width: 100%;
  }
  .filter-row {
    grid-template-columns: 1fr;
    gap: 4px;
  }
  .filter-row-label {
    min-height: 20px;
  }
  .quick-filter-head {
    align-items: flex-start;
    flex-direction: column;
  }
  .quick-filter-fields {
    grid-template-columns: 1fr;
  }
  .account-actions {
    align-items: stretch;
    flex-direction: column;
  }
  .account-actions .q-row,
  .account-actions .q-btn {
    width: 100%;
  }
}
"""
