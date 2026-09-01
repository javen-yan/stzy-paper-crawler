LIGHT_THEME_CSS = """
:root {
  --stzy-accent: #2563eb;
  --stzy-accent-soft: #eff6ff;
  --stzy-border: #e5e7eb;
  --stzy-muted: #667085;
  --stzy-bg: #f8fafc;
  --stzy-danger: #b42318;
}
body {
  background: var(--stzy-bg);
  color: #1f2937;
}
.stzy-shell {
  min-height: 100vh;
  background: var(--stzy-bg);
}
.topbar {
  height: 60px;
  border-bottom: 1px solid var(--stzy-border);
  background: #fff;
}
.topbar-inner {
  width: min(1500px, calc(100vw - 40px));
  margin: 0 auto;
}
.topbar-path {
  width: 240px;
  min-width: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.topbar-path-input {
  flex: 1 1 auto;
  min-width: 0;
}
.topbar-path-input .q-field__inner {
  padding-bottom: 0;
}
.topbar-path-input .q-field {
  min-height: 34px;
}
.topbar-path-input .q-field__control,
.topbar-path-input .q-field__native,
.topbar-path-input .q-field__marginal {
  min-height: 34px;
  height: 34px;
}
.topbar-path-input .q-field__control {
  color: #cbd5e1;
}
.topbar-path-input .q-field__native {
  color: #334155;
  font-size: 13px;
  font-weight: 500;
}
.topbar-path-input .q-field__label {
  top: 4px;
  color: var(--stzy-muted);
  font-size: 11px;
}
.topbar-path-button {
  color: var(--stzy-accent);
  background: var(--stzy-accent-soft);
  margin-left: 2px;
}
.topbar-path-button:hover {
  background: #dbeafe;
}
.panel {
  background: #fff;
  border: 1px solid var(--stzy-border);
  border-radius: 8px;
}
.main-wrap {
  width: min(1500px, calc(100vw - 40px));
  margin: 0 auto;
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
  grid-template-columns: minmax(0, 0.8fr) repeat(4, minmax(0, 1fr)) minmax(96px, 112px);
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
  gap: 12px;
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
.path-grid {
  display: grid;
  width: 100%;
  grid-template-columns: minmax(0, 1fr) 150px;
  gap: 12px;
  align-items: end;
}
.path-grid > *,
.path-grid .q-field {
  width: 100%;
  min-width: 0;
}
.metric-grid {
  display: grid;
  width: 100%;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.step-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
}
.step-dot {
  width: 24px;
  height: 24px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--stzy-accent-soft);
  color: var(--stzy-accent);
  font-size: 13px;
  font-weight: 700;
}
.muted {
  color: var(--stzy-muted);
}
.status-pill {
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 12px;
  background: var(--stzy-accent-soft);
  color: var(--stzy-accent);
}
.log-box {
  display: block;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  height: 150px;
  overflow: auto;
  border-radius: 6px;
  border: 1px solid var(--stzy-border);
  background: #fbfcfd;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  padding: 10px;
}
.runtime-log {
  border-top: 1px solid var(--stzy-border);
  padding-top: 12px;
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
  margin-top: -6px;
}
.task-progress {
  height: 40px;
}
.task-progress-label {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 24px;
  line-height: 1;
  pointer-events: none;
}
.status-overview {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 74px;
  border: 1px solid var(--stzy-border);
  border-radius: 8px;
  background: #f8fafc;
  color: #111827;
  padding: 14px 16px;
  box-sizing: border-box;
}
.status-stage {
  font-size: 20px;
  line-height: 1.25;
  font-weight: 700;
}
.status-detail {
  margin-top: 6px;
  color: var(--stzy-muted);
  font-size: 12px;
  line-height: 1.35;
}
.status-overview strong {
  color: currentColor;
  font-size: 32px;
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
.status-action-grid {
  display: grid;
  width: 100%;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.action-grid .q-btn,
.path-grid .q-btn,
.status-action-grid .q-btn {
  width: 100%;
}
.primary-action {
  height: 44px;
}
.secondary-action {
  height: 44px;
}
.action-grid .q-btn[disabled] {
  opacity: 0.48;
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
.account-actions {
  gap: 12px;
  padding-top: 2px;
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
  padding: 12px;
  background: #fff;
}
.metric-value {
  font-size: 22px;
  line-height: 1;
  font-weight: 700;
  color: #111827;
}
.metric-label {
  margin-top: 6px;
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
    min-height: 60px;
    padding: 8px 0;
  }
  .topbar-inner {
    flex-wrap: wrap;
    gap: 8px;
  }
  .topbar-path {
    width: min(420px, calc(100vw - 40px));
  }
  .workbench,
  .settings-grid,
  .path-grid {
    grid-template-columns: 1fr;
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
  .action-grid,
  .status-action-grid {
    grid-template-columns: 1fr;
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
